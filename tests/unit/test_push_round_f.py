"""Round F — CI-verified gap closure (backend).

Targets the exact missed lines from the last green run:
- app/tasks/grading.py: auto-grade happy/TxError/exception, batch loop, gradebook upsert-create
- app/tasks/video.py: no-variant failure, real tx attachment update, cleanup-on-failure,
  _probe_video, _transcode_variant, celery-absent import guard
- app/modules/admin/routes.py: _find_pg_tool fallbacks, nav-cache failure fallback,
  school-admin guard, bulk schools continue, impersonate-error, subscription timeline,
  payment approve/reject post-commit emails, backup error handlers, settings csrf skip
- app/modules/api/routes.py: school-admin lesson guard, individual/parent search branches,
  form-encoded token, 401/500 handlers
- app/modules/assessment/routes.py: deadline save/submit branches, force-submit paths,
  soft-deleted class 404, wrong-class quiz 404, non-owner 403s, bank error flashes
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import (
    make_attachment,
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_item,
    make_lesson,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"rf-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid


def _quiz(app, cid: int, tid: int, **kw):
    from app.extensions import db
    from app.models.assessment import Quiz

    with app.app_context():
        q = Quiz(
            class_id=cid,
            title=kw.pop("title", "اختبار"),
            duration_min=kw.pop("duration_min", 30),
            created_by=tid,
            status="published",
            **kw,
        )
        db.session.add(q)
        db.session.commit()
        return q.id


def _question(app, quiz_id: int, qtype="mcq"):
    from app.extensions import db
    from app.models.assessment import Question

    with app.app_context():
        if qtype == "mcq":
            options = {"items": [{"label": "أ", "text": "1"}, {"label": "ب", "text": "2"}]}
            correct = {"index": 0}
        elif qtype == "true_false":
            options = None
            correct = {"value": True}
        else:
            options = None
            correct = None
        q = Question(
            quiz_id=quiz_id, type=qtype, prompt=f"سؤال {qtype}", options=options, correct_answer=correct, mark=5.0
        )
        db.session.add(q)
        db.session.commit()
        return q.id


def _attempt(app, quiz_id: int, student_id: int, status="in_progress", started=None):
    from app.extensions import db
    from app.models.assessment import QuizAttempt

    with app.app_context():
        used = QuizAttempt.query.filter_by(quiz_id=quiz_id, student_id=student_id).count()
        att = QuizAttempt(
            quiz_id=quiz_id,
            student_id=student_id,
            attempt_no=used + 1,
            status=status,
            started_at=started or datetime.now(UTC),
        )
        db.session.add(att)
        db.session.commit()
        return att.id


def _answer(app, attempt_id: int, question_id: int, answer):
    from app.extensions import db
    from app.models.assessment import Answer

    with app.app_context():
        db.session.add(Answer(attempt_id=attempt_id, question_id=question_id, answer=answer))
        db.session.commit()


# ═══════════════════════════════════════════════════════════════════════
# Celery guard (pattern from Round D)
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def celery_guard():
    with patch("app.tasks._HAS_CELERY", True):
        mock_celery = MagicMock()

        def _task_dec(*a, **kw):
            if a:
                return a[0]
            return lambda f: f

        mock_celery.task.side_effect = _task_dec
        with patch("app.tasks.celery_app", mock_celery):
            from app.tasks import grading, video  # noqa: F401

            yield


class TestGradingTasksDeep:
    def test_auto_grade_attempt_not_found(self, app, celery_guard):
        from app.tasks.grading import auto_grade_quiz_attempt

        with app.app_context():
            result = auto_grade_quiz_attempt(self=None, attempt_id=99999999)
        assert result["status"] == "failed"
        assert "not found" in result["error"]

    def test_auto_grade_skips_non_submitted(self, app, celery_guard):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        qid = _quiz(app, cid, tid)
        att_id = _attempt(app, qid, stu, status="in_progress")
        from app.tasks.grading import auto_grade_quiz_attempt

        with app.app_context():
            result = auto_grade_quiz_attempt(self=None, attempt_id=att_id)
        assert result["status"] == "skipped"
        assert "submitted" in result["error"]

    def test_auto_grade_happy_mcq_and_essay(self, app, celery_guard):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        qid = _quiz(app, cid, tid)
        mcq_id = _question(app, qid, "mcq")
        essay_id = _question(app, qid, "essay")
        att_id = _attempt(app, qid, stu, status="submitted")
        _answer(app, att_id, mcq_id, {"index": 0})  # correct → awarded
        _answer(app, att_id, essay_id, {"text": "جواب"})  # essay → manual (None)
        from app.tasks.grading import auto_grade_quiz_attempt

        with app.app_context():
            result = auto_grade_quiz_attempt(self=None, attempt_id=att_id)
        assert result["status"] == "completed"
        assert result["score"] == 5.0
        from app.extensions import db
        from app.models.assessment import Answer

        with app.app_context():
            db.session.expire_all()
            essay = db.session.get(Answer, essay_id)
            assert essay is not None

    def test_auto_grade_tx_error_branch(self, app, celery_guard):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        qid = _quiz(app, cid, tid)
        mcq_id = _question(app, qid, "mcq")
        att_id = _attempt(app, qid, stu, status="submitted")
        _answer(app, att_id, mcq_id, {"index": 0})
        from app.core.db import TxError
        from app.tasks.grading import auto_grade_quiz_attempt

        with app.app_context():
            with patch("app.services.assessment._grade_answer", side_effect=TxError("قاعدة بيانات")):
                result = auto_grade_quiz_attempt(self=None, attempt_id=att_id)
        assert result["status"] == "failed"
        assert "قاعدة بيانات" in result["error"]

    def test_auto_grade_generic_exception_branch(self, app, celery_guard):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        qid = _quiz(app, cid, tid)
        mcq_id = _question(app, qid, "mcq")
        att_id = _attempt(app, qid, stu, status="submitted")
        _answer(app, att_id, mcq_id, {"index": 0})
        from app.tasks.grading import auto_grade_quiz_attempt

        with app.app_context():
            with patch("app.services.assessment._grade_answer", side_effect=RuntimeError("boom")):
                result = auto_grade_quiz_attempt(self=None, attempt_id=att_id)
        assert result["status"] == "failed"
        assert "boom" in result["error"]

    def test_batch_grade_mixed_outcomes(self, app, celery_guard):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        qid = _quiz(app, cid, tid)
        _attempt(app, qid, stu, status="submitted")
        _attempt(app, qid, stu, status="submitted")
        _attempt(app, qid, stu, status="submitted")
        import app.tasks.grading as grading_mod
        from app.tasks.grading import batch_grade_quiz

        ok = MagicMock()
        ok.get.return_value = {"status": "completed"}
        bad = MagicMock()
        bad.get.return_value = {"status": "failed"}
        exploded = MagicMock()
        exploded.get.side_effect = RuntimeError("result backend down")
        # .delay() sits outside the try in batch_grade_quiz; .get() failures are
        # what the except-branch guards — exercise all three outcomes.
        with patch.object(grading_mod, "auto_grade_quiz_attempt") as m:
            m.delay.side_effect = [ok, bad, exploded]
            with app.app_context():
                result = batch_grade_quiz(self=None, quiz_id=qid)
        assert result["total"] == 3
        assert result["graded"] == 1
        assert result["failed"] == 2

    def test_batch_gradebook_creates_new_entries(self, app, celery_guard):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        cat = make_grade_category(app, cid, "أعمال", 30)
        item = make_grade_item(app, cid, cat, "واجب 1", 100.0)
        from app.tasks.grading import batch_update_gradebook

        with app.app_context():
            result = batch_update_gradebook(
                self=None,
                class_id=cid,
                grade_item_id=item,
                entries=[{"student_id": stu, "mark": 85.0, "note": "جيد"}],
            )
        assert result["status"] == "completed"
        assert result["updated"] == 1
        from app.extensions import db
        from app.models.gradebook import GradeEntry

        with app.app_context():
            db.session.expire_all()
            row = GradeEntry.query.filter_by(grade_item_id=item, student_id=stu).first()
            assert row is not None
            assert float(row.mark) == 85.0
            assert row.note == "جيد"


class TestVideoTaskInternals:
    def test_import_guard_raises_without_celery(self):
        sys.modules.pop("app.tasks.video", None)
        try:
            with patch("app.tasks._HAS_CELERY", False):
                with pytest.raises(ImportError):
                    __import__("app.tasks.video")
        finally:
            sys.modules.pop("app.tasks.video", None)

    def test_no_variants_generated_fails(self, app, celery_guard, tmp_path, monkeypatch):
        from app.tasks import video

        src = tmp_path / "src.mp4"
        src.write_bytes(b"fake")
        monkeypatch.setattr(video, "_probe_video", lambda p: {"height": 1080})
        monkeypatch.setattr(video, "_transcode_variant", lambda *a, **k: None)
        with app.app_context():
            result = video.transcode_video_to_hls(self=None, lesson_id=11, source_file_path=str(src), school_id=3)
        assert result["status"] == "failed"
        assert "No variants" in result["error"]

    def test_attachment_updated_via_real_tx(self, app, celery_guard, tmp_path, monkeypatch):
        sid, cid = _setup_class(app)
        lid = make_lesson(app, cid)
        make_attachment(app, lid, kind="pdf")
        from app.tasks import video

        src = tmp_path / "hd.mp4"
        src.write_bytes(b"fake")
        monkeypatch.setattr(video, "_probe_video", lambda p: {"height": 1080})
        monkeypatch.setattr(video, "_transcode_variant", lambda *a, **k: "720p.m3u8")
        with app.app_context():
            result = video.transcode_video_to_hls(self=None, lesson_id=lid, source_file_path=str(src), school_id=sid)
        assert result["status"] == "completed"
        from app.extensions import db
        from app.models.content import LessonAttachment

        with app.app_context():
            db.session.expire_all()
            att = LessonAttachment.query.filter_by(lesson_id=lid).first()
            assert att.kind == "video"
            assert att.stored_name == f"protected_media/{sid}/{lid}/master.m3u8"
        if os.path.isdir(result["output_dir"]):
            import shutil

            shutil.rmtree(os.path.dirname(result["output_dir"]), ignore_errors=True)

    def test_failure_after_output_dir_created_cleans_up(self, app, celery_guard, tmp_path, monkeypatch):
        from app.tasks import video

        src = tmp_path / "hd.mp4"
        src.write_bytes(b"fake")
        monkeypatch.setattr(video, "_probe_video", lambda p: {"height": 1080})
        monkeypatch.setattr(video, "_transcode_variant", lambda *a, **k: "720p.m3u8")
        with app.app_context():
            with patch("app.core.db.tx", side_effect=RuntimeError("tx blew up")):
                result = video.transcode_video_to_hls(self=None, lesson_id=12, source_file_path=str(src), school_id=3)
        assert result["status"] == "failed"
        assert "tx blew up" in result["error"]
        assert not os.path.exists(result["output_dir"])

    def test_probe_video_returncode_paths(self, celery_guard):
        from app.tasks import video

        bad = MagicMock(returncode=1, stderr="err")
        with patch("app.tasks.video.subprocess.run", return_value=bad):
            assert video._probe_video("x.mp4") is None
        good = MagicMock(returncode=0, stdout='{"streams": []}')
        with patch("app.tasks.video.subprocess.run", return_value=good):
            assert video._probe_video("x.mp4") == {"streams": []}

    def test_transcode_variant_returncode_paths(self, app, celery_guard, tmp_path):
        from app.tasks import video

        src = tmp_path / "s.mp4"
        src.write_bytes(b"fake")
        key = tmp_path / "enc.key"
        info = tmp_path / "enc.info"
        video._generate_encryption_key(str(key), str(info))
        variant = {"name": "720p", "height": 720, "bitrate": "3000k", "maxrate": "3200k", "bufsize": "3400k"}
        fail = MagicMock(returncode=1, stderr="ffmpeg: bad args")
        with patch("app.tasks.video.subprocess.run", return_value=fail):
            assert video._transcode_variant(str(src), str(tmp_path), variant, str(info)) is None
        ok = MagicMock(returncode=0)
        with patch("app.tasks.video.subprocess.run", return_value=ok):
            assert video._transcode_variant(str(src), str(tmp_path), variant, str(info)) == "720p.m3u8"


# ═════════════════════════════ admin routes ═════════════════════════════


class TestAdminFindPgTool:
    def test_windows_fallback_finds_exe(self, app, tmp_path, monkeypatch):
        import app.modules.admin.routes as admin_mod

        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        exe = tmp_path / "PostgreSQL" / "17" / "bin" / "pg_dump.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("mz")
        monkeypatch.setattr(admin_mod.shutil, "which", lambda name: None)
        result = admin_mod._find_pg_tool("pg_dump")
        assert result == str(exe)

    def test_windows_fallback_returns_name_when_missing(self, app, tmp_path, monkeypatch):
        import app.modules.admin.routes as admin_mod

        monkeypatch.setenv("ProgramFiles", str(tmp_path / "nonexistent"))
        monkeypatch.setattr(admin_mod.shutil, "which", lambda name: None)
        assert admin_mod._find_pg_tool("pg_dump") == "pg_dump"


class TestAdminNavAndGuards:
    def test_nav_context_db_failure_falls_back_to_zeros(self, app):
        import app.modules.admin.routes as admin_mod

        with app.app_context():
            with (
                patch("app.core.cache.get", return_value=None),
                patch("app.models.billing.Subscription.query") as sub_q,
            ):
                sub_q.filter_by.side_effect = RuntimeError("db down")
                data = admin_mod.admin_nav_context()
        assert data == {"subs_pending": 0, "pending_payments": 0, "pending_reg_count": 0}

    def test_school_admin_dashboard_blocks_student(self, app):
        sid = make_school(app)
        _, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, s_email)
        resp = client.get("/admin/school-admin", follow_redirects=False)
        assert resp.status_code == 403

    def test_bulk_action_schools_missing_id_continues(self, app):
        _, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "schools", "action": "delete", "ids": [99999999]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_impersonate_super_admin_target_rejected(self, app):
        _, a_email = mk_user(app, "super_admin")
        other, _ = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.post(f"/admin/users/{other}/impersonate", follow_redirects=False)
        assert resp.status_code == 302
        assert f"/admin/users/{other}" in resp.headers["Location"]

    def test_subscription_detail_active_timeline(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        plan = make_subscription_plan(app, sid, class_id=cid)
        stu, _ = mk_user(app, "student", school_id=sid)
        sub = make_subscription(app, stu, plan, cid, status="active")
        _, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.get(f"/admin/subscriptions/{sub}")
        assert resp.status_code == 200


class TestAdminPaymentReviewEmails:
    def _pending(self, app):
        sid, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, class_id=cid)
        stu, _ = mk_user(app, "student", school_id=sid)
        sub = make_subscription(app, stu, plan, cid, status="pending")
        pay = make_payment(app, sub, status="pending")
        return pay

    def test_approve_sends_post_commit_email(self, app):
        pay = self._pending(app)
        _, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        with patch("app.services.email.send_payment_approved_email") as m:
            resp = client.post(f"/admin/payments/{pay}/approve", follow_redirects=False)
        assert resp.status_code == 302
        m.assert_called_once()

    def test_reject_sends_post_commit_email(self, app):
        pay = self._pending(app)
        _, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        with patch("app.services.email.send_payment_rejected_email") as m:
            resp = client.post(f"/admin/payments/{pay}/reject", follow_redirects=False)
        assert resp.status_code == 302
        m.assert_called_once()


class TestAdminBackupErrorHandlers:
    def _super(self, app):
        _, email = mk_user(app, "super_admin")
        return login_as(app, email)

    def test_backup_create_missing_tool_flash(self, app, tmp_path):
        client = self._super(app)
        with patch.dict(os.environ, {"BACKUP_DIR": str(tmp_path / "bk")}):
            with patch("subprocess.run", side_effect=FileNotFoundError()):
                resp = client.post("/admin/backups/create", follow_redirects=False)
        assert resp.status_code == 302

    def test_backup_create_generic_error_flash(self, app, tmp_path):
        client = self._super(app)
        with patch.dict(os.environ, {"BACKUP_DIR": str(tmp_path / "bk2")}):
            with patch("subprocess.run", side_effect=RuntimeError("timeout")):
                resp = client.post("/admin/backups/create", follow_redirects=False)
        assert resp.status_code == 302

    def test_backup_restore_missing_tool_flash(self, app, tmp_path):
        client = self._super(app)
        bk = tmp_path / "bk3"
        bk.mkdir()
        (bk / "d.sql").write_text("-- dump")
        with patch.dict(os.environ, {"BACKUP_DIR": str(bk)}):
            with patch("subprocess.run", side_effect=FileNotFoundError()):
                resp = client.post("/admin/backups/d.sql/restore", data={"confirm": "yes"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_backup_restore_generic_error_flash(self, app, tmp_path):
        client = self._super(app)
        bk = tmp_path / "bk4"
        bk.mkdir()
        (bk / "d2.sql").write_text("-- dump")
        with patch.dict(os.environ, {"BACKUP_DIR": str(bk)}):
            with patch("subprocess.run", side_effect=RuntimeError("boom")):
                resp = client.post("/admin/backups/d2.sql/restore", data={"confirm": "yes"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_backup_restore_without_database_url(self, app, tmp_path, monkeypatch):
        client = self._super(app)
        bk = tmp_path / "bk5"
        bk.mkdir()
        (bk / "d3.sql").write_text("-- dump")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch.dict(os.environ, {"BACKUP_DIR": str(bk)}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            resp = client.post("/admin/backups/d3.sql/restore", data={"confirm": "yes"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_settings_save_skips_csrf_key(self, app):
        client = self._super(app)
        resp = client.post("/admin/settings", data={"csrf_token": "x", "site_name": "أزاد"}, follow_redirects=False)
        assert resp.status_code == 302
        from app.models.system import Setting

        with app.app_context():
            row = Setting.query.filter_by(key="site_name").first()
            assert row is not None and row.value == "أزاد"
            csrf = Setting.query.filter_by(key="csrf_token").first()
            assert csrf is None


# ═════════════════════════════ API routes ═════════════════════════════


class TestApiRouteBranches:
    def test_lesson_school_admin_cross_school_403(self, app):
        sid_a, cid_a = _setup_class(app)
        lid = make_lesson(app, cid_a)
        sid_b, _ = _setup_class(app)
        _, b_email = mk_user(app, "school_admin", school_id=sid_b)
        client = login_as(app, b_email)
        resp = client.get(f"/api/v1/lessons/{lid}")
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_lesson_school_admin_same_school_ok(self, app):
        sid, cid = _setup_class(app)
        lid = make_lesson(app, cid)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        resp = client.get(f"/api/v1/lessons/{lid}")
        assert resp.status_code == 200

    def test_classes_list_individual_member_scope(self, app):
        from tests.conftest import make_individual_user

        make_individual_user(app)
        from tests.conftest import _uid

        # individual helper returns only id — login via a fresh user with no school
        email = f"ind-{_uid()}@test.com"
        uid = make_individual_user(app, email=email)
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            email = db.session.get(User, uid).email
        client = app.test_client()
        client.post("/auth/login", data={"email": email, "password": PASSWORD})
        resp = client.get("/api/v1/classes")
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []

    def test_search_parent_without_school_empty_scopes(self, app):
        _, p_email = mk_user(app, "parent")
        client = login_as(app, p_email)
        resp = client.get("/api/v1/search?q=ab")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["users"] == []
        assert data["subscriptions"] == []

    def test_search_school_admin_scopes_by_school(self, app):
        sid, cid = _setup_class(app)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        resp = client.get("/api/v1/search?q=مستخدم")
        assert resp.status_code == 200

    def test_token_endpoint_form_encoded(self, app):
        sid = make_school(app)
        _, email = mk_user(app, "student", school_id=sid)
        client = app.test_client()
        resp = client.post("/api/v1/auth/token", data={"email": email, "password": PASSWORD})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["token_type"] == "Bearer"

    def test_me_unauthenticated_401_handler(self, app):
        client = app.test_client()
        resp = client.get("/api/v1/me")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"

    def test_internal_error_handler_shape(self, app):
        from app.modules.api.routes import api_500

        with app.test_request_context("/api/v1/x"):
            resp, status = api_500(Exception("x"))
        assert status == 500
        assert resp.json["error"]["code"] == "INTERNAL_ERROR"


# ═════════════════════════════ assessment routes ═════════════════════════════


class TestAssessmentDeadlineAndErrors:
    def test_soft_deleted_class_404_on_attempt_start(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            db.session.get(ClassRoom, cid).deleted_at = datetime.now(UTC)
            db.session.commit()
        stu, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/quizzes/{qid}/attempt", follow_redirects=False)
        assert resp.status_code == 404

    def test_quiz_manage_wrong_class_404(self, app):
        sid, cid = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        _, cid2 = _setup_class(app)
        # teacher must be able to teach cid2 to pass the decorator before the
        # route's own wrong-class check fires

        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            db.session.get(ClassRoom, cid2).teacher_id = tid
            db.session.commit()
        client = login_as(app, t_email)
        resp = client.get(f"/classes/{cid2}/quizzes/{qid}", follow_redirects=False)
        assert resp.status_code == 404

    def test_attempt_start_exhausted_attempts_flash(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid, attempts_allowed=1)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        _attempt(app, qid, stu, status="submitted")
        client = login_as(app, s_email)
        resp = client.get(f"/classes/quizzes/{qid}/attempt", follow_redirects=False)
        assert resp.status_code == 302
        assert "quizzes" in resp.headers["Location"]

    def test_attempt_do_owner_without_membership_403(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        stu, s_email = mk_user(app, "student", school_id=sid)  # no ClassMember
        att_id = _attempt(app, qid, stu)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/attempt/{att_id}", follow_redirects=False)
        assert resp.status_code == 403

    def test_attempt_save_by_non_owner_403(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        stu, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu)
        other, o_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, o_email)
        resp = client.post(f"/classes/attempt/{att_id}/save", data={}, follow_redirects=False)
        assert resp.status_code == 403

    def test_attempt_save_empty_form_continues_and_saves(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        _question(app, qid, "mcq")
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu)
        client = login_as(app, s_email)
        resp = client.post(f"/classes/attempt/{att_id}/save", data={}, follow_redirects=False)
        assert resp.status_code == 302

    def test_attempt_save_after_deadline_rejected(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid, duration_min=1)
        q_id = _question(app, qid, "mcq")
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu, started=datetime.now(UTC) - timedelta(hours=2))
        client = login_as(app, s_email)
        resp = client.post(f"/classes/attempt/{att_id}/save", data={f"q_{q_id}": "0"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_attempt_submit_by_non_owner_403(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        stu, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu)
        other, o_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, o_email)
        resp = client.post(f"/classes/attempt/{att_id}/submit", data={}, follow_redirects=False)
        assert resp.status_code == 403

    def test_attempt_submit_after_deadline_grades_saved_answers(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid, duration_min=1)
        q_id = _question(app, qid, "mcq")
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu, started=datetime.now(UTC) - timedelta(hours=2))
        client = login_as(app, s_email)
        with patch("app.services.email.send_quiz_result_email"):
            resp = client.post(f"/classes/attempt/{att_id}/submit", data={f"q_{q_id}": "0"}, follow_redirects=False)
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            db.session.expire_all()
            att = db.session.get(QuizAttempt, att_id)
            assert att.status == "submitted"
            assert att.score is not None

    def test_attempt_result_unknown_404(self, app):
        _, s_email = mk_user(app, "student")
        client = login_as(app, s_email)
        resp = client.get("/classes/attempt/99999999/result", follow_redirects=False)
        assert resp.status_code == 404

    def test_answer_grade_by_student_403(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        essay_id = _question(app, qid, "essay")
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu, status="submitted")
        _answer(app, att_id, essay_id, {"text": "x"})
        from app.models.assessment import Answer

        with app.app_context():
            ans_id = Answer.query.filter_by(attempt_id=att_id).first().id
        client = login_as(app, s_email)
        resp = client.post(f"/classes/answers/{ans_id}/grade", data={"mark": "4"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_bank_create_empty_text_flash(self, app):
        sid = make_school(app)
        _, t_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, t_email)
        resp = client.post(
            "/classes/question-bank/new",
            data={"question_text": "", "question_type": "mcq", "difficulty": "3"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_bank_delete_other_teacher_flash(self, app):
        sid = make_school(app)
        t1, _ = mk_user(app, "teacher", school_id=sid)
        from app.services.question_bank import create_bank_question

        with app.app_context():
            bq, err = create_bank_question(teacher_id=t1, school_id=sid, question_text="س", question_type="mcq")
            assert err is None
            bq_id = bq.id
        _, t2_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, t2_email)
        resp = client.post(f"/classes/question-bank/{bq_id}/delete", follow_redirects=False)
        assert resp.status_code == 302

    def test_bank_import_page_student_403(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/quiz/{qid}/bank-import", follow_redirects=False)
        assert resp.status_code == 403

    def test_bank_import_action_student_403(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        client = login_as(app, s_email)
        resp = client.post(f"/classes/quiz/{qid}/bank-import", data={}, follow_redirects=False)
        assert resp.status_code == 403

    def test_quiz_stats_student_403(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/quiz/{qid}/stats", follow_redirects=False)
        assert resp.status_code == 403


class TestAssessmentProctoringForceSubmit:
    def _setup_with_logs(self, app, tab_switches=3):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid, max_tab_switches=3)
        q_id = _question(app, qid, "mcq")
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu)
        from app.extensions import db
        from app.models.assessment import ProctoringLog

        with app.app_context():
            for _ in range(tab_switches):
                db.session.add(ProctoringLog(attempt_id=att_id, event_type="tab_switch"))
            db.session.commit()
        return att_id, q_id, s_email

    def test_tab_switch_exceeded_submits_saved_answers(self, app):
        att_id, q_id, s_email = self._setup_with_logs(app)
        client = login_as(app, s_email)
        resp = client.post(
            f"/classes/attempt/{att_id}/proctor",
            data=json.dumps({"event_type": "tab_switch", f"q_{q_id}": "0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["auto_submit"] is True
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            db.session.expire_all()
            assert db.session.get(QuizAttempt, att_id).status == "submitted"

    def test_tab_switch_exceeded_after_deadline_breaks_then_submits(self, app):
        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        qid = _quiz(app, cid, tid, max_tab_switches=1, duration_min=1)
        q_id = _question(app, qid, "mcq")
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        att_id = _attempt(app, qid, stu, started=datetime.now(UTC) - timedelta(hours=2))
        from app.extensions import db
        from app.models.assessment import ProctoringLog

        with app.app_context():
            db.session.add(ProctoringLog(attempt_id=att_id, event_type="tab_switch"))
            db.session.commit()
        client = login_as(app, s_email)
        resp = client.post(
            f"/classes/attempt/{att_id}/proctor",
            data=json.dumps({"event_type": "tab_switch", f"q_{q_id}": "0"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["reason"] == "tab_switches_exceeded"
