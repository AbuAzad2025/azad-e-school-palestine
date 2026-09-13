"""Extended coverage round D — admin bulk branches, video task internals, content/grades edges.

Targets CI-verified missed lines (run 34777509233, backend 92.32% lines / 79.04% branches):
- app/modules/admin/routes.py: bulk activate/delete + schools branch, user_detail,
  backup create/restore subprocess paths, registration approve happy path,
  settings save update branch, impersonation start error + exit success
- app/tasks/video.py: transcode happy path with mocked ffmpeg, variant skip,
  master playlist writer, exception-cleanup path
- app/modules/content/routes.py: attachment upload (success + TxError), lesson_create,
  lesson_import success + 403 target, offline mark existing branch, offline remove own
- app/modules/grades/routes.py: submission grade by teacher, appeal review, rubric grade save,
  report-card pdf fallback, gradebook student-vs-teacher templates
- app/modules/assessment/routes.py: attempt_do non-in_progress redirect, quiz_new error path,
  answer_grade, bank question delete, ai_generate_questions permission branch
- app/modules/tutoring/routes.py: profile 404, self-book guard, payout form post,
  rate-window expiry branch, session update by student 403
- app/modules/schools/routes.py: onboarding already-complete redirect, onboarding save final step
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_item,
    make_lesson,
    make_school,
    make_subject,
    make_tutor_profile,
    make_tutoring_session,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"xd-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def persona(app, role: str, school_id=None):
    uid, email = mk_user(app, role, school_id)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid, gid


def _set_class_teacher(app, cid: int, tid: int):
    from app.extensions import db
    from app.models.class_room import ClassRoom

    with app.app_context():
        db.session.get(ClassRoom, cid).teacher_id = tid
        db.session.commit()


# ═════════════════════════════ admin ═════════════════════════════


class TestAdminBulkActionsDeep:
    def test_bulk_activate_and_delete_users(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        sid = make_school(app)
        t1, _ = mk_user(app, "teacher", school_id=sid)
        t2, _ = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, a_email)

        # deactivate first so activate has effect
        client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "users", "action": "deactivate", "ids": [t1]}),
            content_type="application/json",
        )
        resp = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "users", "action": "activate", "ids": [t1]}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # soft-delete t2
        resp2 = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "users", "action": "delete", "ids": [t2]}),
            content_type="application/json",
        )
        assert resp2.status_code == 200

        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            db.session.expire_all()
            assert db.session.get(User, t1).is_active is True
            u2 = db.session.get(User, t2)
            assert u2.is_active is False
            assert u2.deleted_at is not None

    def test_bulk_action_skips_self_and_unknown_ids(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        # includes self (skipped) and a non-existent id (skipped)
        resp = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "users", "action": "deactivate", "ids": [admin_id, 999999]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            db.session.expire_all()
            assert db.session.get(User, admin_id).is_active is True

    def test_bulk_action_schools_delete(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        sid1 = make_school(app)
        sid2 = make_school(app)
        client = login_as(app, a_email)
        resp = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "schools", "action": "delete", "ids": [sid1, sid2]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.school import School

        with app.app_context():
            db.session.expire_all()
            assert db.session.get(School, sid1).is_active is False
            assert db.session.get(School, sid2).is_active is False

    def test_bulk_action_schools_rejects_activate(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "schools", "action": "activate", "ids": [1]}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_user_detail_renders(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        tid, _ = mk_user(app, "teacher", school_id=make_school(app))
        client = login_as(app, a_email)
        resp = client.get(f"/admin/users/{tid}")
        assert resp.status_code == 200


class TestAdminBackupsSubprocess:
    def test_backup_create_success(self, app, tmp_path):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        backup_dir = tmp_path / "bk"
        fake_result = MagicMock()
        fake_result.returncode = 0

        def _fake_run(cmd, **kwargs):
            # route writes nothing itself — create the file to prove flow
            filepath = cmd[3]
            with open(filepath, "w") as f:
                f.write("-- dump")
            return fake_result

        with patch.dict("os.environ", {"BACKUP_DIR": str(backup_dir)}):
            with patch("subprocess.run", side_effect=_fake_run):
                resp = client.post("/admin/backups/create", follow_redirects=False)
        assert resp.status_code == 302
        assert any(p.name.startswith("backup_") for p in backup_dir.iterdir())

    def test_backup_create_failure_reports_stderr(self, app, tmp_path):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stderr = "pg_dump: too many arguments"
        with patch.dict("os.environ", {"BACKUP_DIR": str(tmp_path / "bk2")}):
            with patch("subprocess.run", return_value=fake_result):
                resp = client.post("/admin/backups/create", follow_redirects=False)
        assert resp.status_code == 302

    def test_backup_restore_success_with_confirm(self, app, tmp_path):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        backup_dir = tmp_path / "bk3"
        backup_dir.mkdir()
        (backup_dir / "real.sql").write_text("-- dump")
        fake_result = MagicMock()
        fake_result.returncode = 0
        with patch.dict("os.environ", {"BACKUP_DIR": str(backup_dir)}):
            with patch("subprocess.run", return_value=fake_result):
                resp = client.post(
                    "/admin/backups/real.sql/restore",
                    data={"confirm": "yes"},
                    follow_redirects=False,
                )
        assert resp.status_code == 302

    def test_backup_restore_failure_reports_stderr(self, app, tmp_path):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        backup_dir = tmp_path / "bk4"
        backup_dir.mkdir()
        (backup_dir / "bad.sql").write_text("-- dump")
        fake_result = MagicMock()
        fake_result.returncode = 2
        fake_result.stderr = "psql: FATAL"
        with patch.dict("os.environ", {"BACKUP_DIR": str(backup_dir)}):
            with patch("subprocess.run", return_value=fake_result):
                resp = client.post(
                    "/admin/backups/bad.sql/restore",
                    data={"confirm": "yes"},
                    follow_redirects=False,
                )
        assert resp.status_code == 302


class TestAdminImpersonationDeep:
    def test_impersonate_self_rejected(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.post(f"/admin/users/{admin_id}/impersonate", follow_redirects=True)
        assert resp.status_code == 200

    def test_impersonate_inactive_target_rejected(self, app):
        from app.extensions import db
        from app.models.user import User

        admin_id, a_email = mk_user(app, "super_admin")
        tid, _ = mk_user(app, "teacher", school_id=make_school(app))
        with app.app_context():
            db.session.get(User, tid).is_active = False
            db.session.commit()
        client = login_as(app, a_email)
        resp = client.post(f"/admin/users/{tid}/impersonate", follow_redirects=True)
        assert resp.status_code == 200

    def test_impersonate_and_exit_roundtrip(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, a_email)
        # start
        resp = client.post(f"/admin/users/{tid}/impersonate", follow_redirects=False)
        assert resp.status_code == 302
        # exit while impersonating (actor = original super admin)
        resp2 = client.post("/admin/impersonate/exit", follow_redirects=False)
        assert resp2.status_code == 302


class TestAdminRegistrationApprove:
    def test_approve_pending_user(self, app):
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus
        from tests.conftest import make_user as _mk

        admin_id, a_email = mk_user(app, "super_admin")
        uid = _mk(app, role="student", school_id=make_school(app), approved=False)
        with app.app_context():
            db.session.get(User, uid).approval_status = UserApprovalStatus.pending
            db.session.commit()
        client = login_as(app, a_email)
        resp = client.post(f"/admin/registrations/{uid}/approve", follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            db.session.expire_all()
            assert db.session.get(User, uid).approval_status == UserApprovalStatus.approved


class TestAdminSettingsUpdate:
    def test_settings_save_updates_existing(self, app):
        from app.extensions import db
        from app.models.system import Setting

        with app.app_context():
            db.session.add(Setting(key="motto", value="قديم"))
            db.session.commit()

        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.post("/admin/settings", data={"motto": "جديد"}, follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            setting = db.session.query(Setting).filter_by(key="motto").first()
            assert setting.value == "جديد"


# ═════════════════════════════ video tasks ═════════════════════════════


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
            from app.tasks import grading, notifications, reports, video  # noqa: F401

            yield


class TestVideoTaskTranscodeHappy:
    def test_transcode_low_res_source_fallback(self, app, celery_guard, tmp_path, monkeypatch):
        """Source below 720p → 'source' variant fallback, master playlist, tx update."""
        from app.tasks import video

        src = tmp_path / "src.mp4"
        src.write_bytes(b"fake")

        monkeypatch.setattr(video, "_probe_video", lambda p: {"height": 480})
        monkeypatch.setattr(video, "_transcode_variant", lambda *a, **k: "source.m3u8")
        # real _generate_encryption_key + _create_master_playlist run for real
        with app.app_context():
            with patch("app.core.db.tx") as mock_tx:
                result = video.transcode_video_to_hls(
                    self=None,
                    lesson_id=7,
                    source_file_path=str(src),
                    school_id=3,
                )
        assert result["status"] == "completed"
        assert result["error"] is None
        assert mock_tx.called
        # master playlist was written into the protected output dir
        import os

        assert os.path.isdir(result["output_dir"])
        master = os.path.join(result["output_dir"], "master.m3u8")
        with open(master) as f:
            content = f.read()
        assert "#EXTM3U" in content
        assert "source.m3u8" in content

    def test_transcode_high_res_two_variants(self, app, celery_guard, tmp_path, monkeypatch):
        from app.tasks import video

        src = tmp_path / "hd.mp4"
        src.write_bytes(b"fake")
        monkeypatch.setattr(video, "_probe_video", lambda p: {"height": 1080})

        def _fake_variant(source, out_dir, variant, key_info):
            return f"{variant['name']}.m3u8"

        monkeypatch.setattr(video, "_transcode_variant", _fake_variant)
        with app.app_context():
            with patch("app.core.db.tx"):
                result = video.transcode_video_to_hls(self=None, lesson_id=8, source_file_path=str(src), school_id=3)
        assert result["status"] == "completed"
        with open(result["output_dir"] + "/master.m3u8") as f:
            content = f.read()
        assert "720p.m3u8" in content and "1080p.m3u8" in content

    def test_transcode_exception_cleans_up(self, app, celery_guard, tmp_path, monkeypatch):
        """If a step raises mid-pipeline, temp/output dirs are removed and status failed."""
        from app.tasks import video

        src = tmp_path / "boom.mp4"
        src.write_bytes(b"fake")
        monkeypatch.setattr(video, "_probe_video", lambda p: {"height": 1080})

        def _explode(*a, **k):
            raise RuntimeError("ffmpeg exploded")

        monkeypatch.setattr(video, "_generate_encryption_key", _explode)
        with app.app_context():
            result = video.transcode_video_to_hls(self=None, lesson_id=9, source_file_path=str(src), school_id=3)
        assert result["status"] == "failed"
        assert "ffmpeg exploded" in result["error"]
        # temp dir cleaned up
        import glob
        import os

        leftovers = [d for d in glob.glob(os.path.join(tmp_path, "protected_media", "**"), recursive=False)]
        for d in leftovers:
            assert not os.path.exists(d) or not any(os.scandir(d))

    def test_create_master_playlist_bandwidths(self, celery_guard, tmp_path):
        from app.tasks.video import _create_master_playlist

        path = _create_master_playlist(
            str(tmp_path),
            [
                {"name": "720p", "playlist": "720p.m3u8"},
                {"name": "1080p", "playlist": "1080p.m3u8"},
                {"name": "custom", "playlist": "custom.m3u8"},
            ],
        )
        content = open(path).read()
        assert "BANDWIDTH=3000000" in content
        assert "BANDWIDTH=5500000" in content
        assert "BANDWIDTH=2200000" in content  # unknown name fallback


# ═════════════════════════════ content ═════════════════════════════


class TestContentUploadAndImport:
    def _teacher_lesson(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        lid = make_lesson(app, cid)
        return sid, cid, lid, tid, t_email

    def test_lesson_create_success(self, app):
        sid, cid, _, _, t_email = self._teacher_lesson(app)
        client = login_as(app, t_email)
        assert client.get(f"/classes/{cid}/lessons/new").status_code == 200
        resp = client.post(
            f"/classes/{cid}/lessons",
            data={"title": "درس جديد", "body_html": "<p>المحتوى</p>"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/lessons/" in resp.headers["Location"]

    def test_lesson_update_by_teacher(self, app):
        _, cid, lid, _, t_email = self._teacher_lesson(app)
        client = login_as(app, t_email)
        resp = client.post(
            f"/classes/{cid}/lessons/{lid}",
            data={"title": "عنوان محدّث", "body_html": "<p>جديد</p>", "unit_id": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_lesson_import_success(self, app):
        sid, cid, lid, tid, t_email = self._teacher_lesson(app)
        # second class in the SAME school, taught by the SAME teacher persona
        cid2 = make_class(app, sid, make_grade(app, sid, grade_level=_next_level(sid)), make_subject(app))
        _set_class_teacher(app, cid2, tid)
        # share the source lesson
        from app.extensions import db
        from app.models.content import Lesson

        with app.app_context():
            db.session.get(Lesson, lid).is_shared = True
            db.session.commit()

        client = login_as(app, t_email)
        resp = client.post(
            f"/classes/import/{lid}",
            data={"target_class_id": str(cid2)},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_lesson_import_forbidden_target(self, app):
        sid, cid, lid, _, t_email = self._teacher_lesson(app)
        from app.extensions import db
        from app.models.content import Lesson

        with app.app_context():
            db.session.get(Lesson, lid).is_shared = True
            db.session.commit()
        # target in another school taught by someone else
        other_sid = make_school(app)
        cid2 = make_class(
            app, other_sid, make_grade(app, other_sid, grade_level=_next_level(other_sid)), make_subject(app)
        )
        client = login_as(app, t_email)
        resp = client.post(
            f"/classes/import/{lid}",
            data={"target_class_id": str(cid2)},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_offline_mark_then_duplicate(self, app):
        sid, cid, lid, _, _ = self._teacher_lesson(app)
        from tests.conftest import make_attachment

        att_id = make_attachment(app, lid, kind="video")
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        client = login_as(app, s_email)
        resp = client.post(
            "/classes/offline/mark",
            data={"attachment_id": str(att_id), "lesson_id": str(lid)},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # duplicate → warning branch
        resp2 = client.post(
            "/classes/offline/mark",
            data={"attachment_id": str(att_id), "lesson_id": str(lid)},
            follow_redirects=False,
        )
        assert resp2.status_code == 302

    def test_offline_remove_own_download(self, app):
        sid, cid, lid, _, _ = self._teacher_lesson(app)
        from app.extensions import db
        from app.models.offline import OfflineDownload
        from tests.conftest import make_attachment

        att_id = make_attachment(app, lid, kind="video")
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        with app.app_context():
            dl = OfflineDownload(student_id=stu_id, attachment_id=att_id, lesson_id=lid)
            db.session.add(dl)
            db.session.commit()
            dl_id = dl.id
        client = login_as(app, s_email)
        resp = client.post(f"/classes/offline/{dl_id}/remove", follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            assert db.session.get(OfflineDownload, dl_id) is None


# ═════════════════════════════ grades ═════════════════════════════


class TestGradesDeep:
    def _full_setup(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        return sid, cid, tid, t_email, stu_id, s_email

    def _assignment_and_submission(self, app, cid: int, stu_id: int):
        from app.extensions import db
        from app.models.gradebook import Assignment, Submission

        with app.app_context():
            asg = Assignment(class_id=cid, title="واجب", body="اكتب", max_mark=20, created_by=1)
            db.session.add(asg)
            db.session.commit()
            sub = Submission(assignment_id=asg.id, student_id=stu_id, body="حل الطالب")
            db.session.add(sub)
            db.session.commit()
            return asg.id, sub.id

    def test_submission_grade_by_teacher(self, app):
        sid, cid, _, t_email, stu_id, _ = self._full_setup(app)
        _, sub_id = self._assignment_and_submission(app, cid, stu_id)
        client = login_as(app, t_email)
        resp = client.post(
            f"/classes/submissions/{sub_id}/grade",
            data={"mark": "17.5", "feedback": "جيد جداً"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.gradebook import Submission

        with app.app_context():
            db.session.expire_all()
            sub = db.session.get(Submission, sub_id)
            assert float(sub.mark) == 17.5
            assert sub.graded_by is not None

    def test_submission_grade_denies_other_teacher(self, app):
        sid, cid, _, _, stu_id, _ = self._full_setup(app)
        _, sub_id = self._assignment_and_submission(app, cid, stu_id)
        other, o_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, o_email)
        resp = client.post(f"/classes/submissions/{sub_id}/grade", data={"mark": "10"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_appeal_flow_submit_then_review(self, app):
        sid, cid, _, t_email, stu_id, s_email = self._full_setup(app)
        _, sub_id = self._assignment_and_submission(app, cid, stu_id)
        sclient = login_as(app, s_email)
        resp = sclient.post(
            f"/classes/submissions/{sub_id}/appeal",
            data={"reason": "الدرجة أقل من المستحق"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # duplicate appeal → warning branch
        resp2 = sclient.post(
            f"/classes/submissions/{sub_id}/appeal",
            data={"reason": "مرة أخرى"},
            follow_redirects=False,
        )
        assert resp2.status_code == 302

        from app.extensions import db
        from app.models.gradebook import GradeAppeal

        with app.app_context():
            appeal = db.session.query(GradeAppeal).filter_by(submission_id=sub_id).first()
            appeal_id = appeal.id
        tclient = login_as(app, t_email)
        resp3 = tclient.post(
            f"/classes/appeals/{appeal_id}/review",
            data={"action": "approved", "response": "تمت المراجعة"},
            follow_redirects=False,
        )
        assert resp3.status_code == 302
        with app.app_context():
            db.session.expire_all()
            assert db.session.get(GradeAppeal, appeal_id).status == "approved"

    def test_report_card_pdf_fallback_when_no_renderer(self, app):
        sid, cid, _, _, stu_id, s_email = self._full_setup(app)
        client = login_as(app, s_email)
        with patch("app.services.report_card.render_report_card_pdf", return_value=None):
            resp = client.get(f"/classes/{cid}/report-card/{stu_id}/pdf", follow_redirects=False)
        assert resp.status_code == 302

    def test_gradebook_teacher_sees_entries(self, app):
        sid, cid, _, t_email, stu_id, _ = self._full_setup(app)
        cat_id = make_grade_category(app, cid, "اختبارات", 50)
        item_id = make_grade_item(app, cid, cat_id, "اختبار 1", 20)
        from tests.conftest import make_grade_entry

        make_grade_entry(app, stu_id, item_id, 18)
        client = login_as(app, t_email)
        resp = client.get(f"/classes/{cid}/gradebook")
        assert resp.status_code == 200


# ═════════════════════════════ assessment ═════════════════════════════


def _quiz(app, cid: int, tid: int, title="اختبار"):
    from app.extensions import db
    from app.models.assessment import Quiz

    with app.app_context():
        q = Quiz(class_id=cid, title=title, duration_min=30, created_by=tid, status="published")
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


class TestAssessmentEdges:
    def _attempt(self, app, cid: int, tid: int, stu_id: int, qtype="essay"):
        qid = _quiz(app, cid, tid)
        q_id = _question(app, qid, qtype=qtype)
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            att = QuizAttempt(quiz_id=qid, student_id=stu_id, status="in_progress")
            db.session.add(att)
            db.session.commit()
            return att.id, q_id

    def test_attempt_do_already_submitted_redirects(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            db.session.get(QuizAttempt, att_id).status = "submitted"
            db.session.commit()
        client = login_as(app, s_email)
        resp = client.get(f"/classes/attempt/{att_id}", follow_redirects=False)
        assert resp.status_code == 302

    def test_attempt_result_owner_after_submit(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            db.session.get(QuizAttempt, att_id).status = "submitted"
            db.session.commit()
        client = login_as(app, s_email)
        resp = client.get(f"/classes/attempt/{att_id}/result")
        assert resp.status_code == 200

    def test_attempt_result_by_teacher(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        client = login_as(app, t_email)
        resp = client.get(f"/classes/attempt/{att_id}/result")
        assert resp.status_code == 200

    def test_answer_grade_by_teacher(self, app):
        sid, cid, tid, t_email, stu_id, _ = self._attempt_setup(app)
        att_id, q_id = self._mk_attempt(app, cid, stu_id, tid)
        from app.extensions import db
        from app.models.assessment import Answer

        with app.app_context():
            ans = Answer(attempt_id=att_id, question_id=q_id, answer={"text": "مقالي"}, is_correct=None)
            db.session.add(ans)
            db.session.commit()
            ans_id = ans.id
        client = login_as(app, t_email)
        resp = client.post(f"/classes/answers/{ans_id}/grade", data={"mark": "4"}, follow_redirects=False)
        assert resp.status_code == 302

    def _attempt_setup(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        return sid, cid, tid, t_email, stu_id, None

    def _mk_attempt(self, app, cid: int, stu_id: int, tid: int):
        return self._attempt(app, cid, tid, stu_id)

    def test_bank_question_delete(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        from app.extensions import db
        from app.models.question_bank import QuestionBank

        with app.app_context():
            bq = QuestionBank(
                teacher_id=tid,
                school_id=sid,
                question_text="سؤال بنك",
                question_type="true_false",
                correct_answer={"value": True},
                difficulty=3,
            )
            db.session.add(bq)
            db.session.commit()
            bq_id = bq.id
        client = login_as(app, t_email)
        resp = client.post(f"/classes/question-bank/{bq_id}/delete", follow_redirects=False)
        assert resp.status_code == 302

    def test_ai_generate_questions_denies_student(self, app):
        sid = make_school(app)
        uid, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, s_email)
        resp = client.post(
            "/classes/quiz/generate-ai",
            data=json.dumps({"topic": "رياضيات"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_ai_generate_questions_teacher_mock(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, t_email)
        resp = client.post(
            "/classes/quiz/generate-ai",
            data=json.dumps({"topic": "الكسور", "count": 2}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "questions" in data


# ═════════════════════════════ tutoring ═════════════════════════════


class TestTutoringEdges:
    def test_profile_404_for_missing(self, app):
        client = app.test_client()
        resp = client.get("/tutoring/tutors/999999", follow_redirects=False)
        assert resp.status_code == 404

    def test_book_self_guard(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        make_tutor_profile(app, tid)
        client = login_as(app, t_email)
        resp = client.post(f"/tutoring/book/{tid}", data={}, follow_redirects=False)
        assert resp.status_code == 302

    def test_book_price_out_of_range(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        make_tutor_profile(app, tid, price_hour=100.0)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, s_email)
        resp = client.post(
            f"/tutoring/book/{tid}",
            data={
                "subject": "رياضيات",
                "preferred_time": "2026-10-01T10:00",
                "mode": "offline",
                "price_quote": "10",  # far below 80% of 100
                "note": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200  # re-renders with error

    def test_session_update_by_student_403(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu_id, status="requested", price=100.0)
        client = login_as(app, s_email)
        resp = client.post(
            f"/tutoring/sessions/{sess_id}",
            data={"scheduled_at": "2026-10-01T10:00", "mode": "online"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_session_status_cancelled(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu_id, status="requested", price=100.0)
        client = login_as(app, t_email)
        resp = client.get(f"/tutoring/sessions/{sess_id}/status/cancelled", follow_redirects=False)
        assert resp.status_code == 302

    def test_payout_request_too_small(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        make_tutor_profile(app, tid)
        client = login_as(app, t_email)
        resp = client.post("/tutoring/payout-request", data={"amount": "50"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_rate_window_expired(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(
            app,
            tid,
            stu_id,
            status="completed",
            price=100.0,
            end_time=datetime.now(UTC) - timedelta(hours=48),
        )
        client = login_as(app, s_email)
        resp = client.post(f"/tutoring/rate/{sess_id}", data={"rating": "5"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_rate_duplicate_rejected(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(
            app,
            tid,
            stu_id,
            status="completed",
            price=100.0,
            end_time=datetime.now(UTC) - timedelta(hours=1),
        )
        from tests.conftest import make_tutor_review

        make_tutor_review(app, sess_id, stu_id, rating=4)
        client = login_as(app, s_email)
        resp = client.post(f"/tutoring/rate/{sess_id}", data={"rating": "5"}, follow_redirects=False)
        assert resp.status_code == 302


# ═════════════════════════════ schools ═════════════════════════════


class TestSchoolsOnboarding:
    def test_onboarding_already_complete_redirects(self, app):
        from app.extensions import db
        from app.models.system import OnboardingProgress

        sid = make_school(app)
        admin_id, a_email = mk_user(app, "school_admin", school_id=sid)
        with app.app_context():
            db.session.add(
                OnboardingProgress(
                    school_id=sid,
                    current_step=5,
                    total_steps=5,
                    completed_steps={},
                    is_complete=True,
                )
            )
            db.session.commit()
        client = login_as(app, a_email)
        resp = client.get("/schools/onboarding/1", follow_redirects=False)
        assert resp.status_code == 302

    def test_onboarding_save_final_step(self, app):
        sid = make_school(app)
        admin_id, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        resp = client.post("/schools/onboarding/5", data={"final": "نعم"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_join_class_twice_rejected(self, app):
        sid, cid, _ = _setup_class(app)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            code = db.session.get(ClassRoom, cid).join_code
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, s_email)
        first = client.post("/schools/classes/join", data={"code": code}, follow_redirects=False)
        assert first.status_code == 302
        # second join → duplicate flash branch (redirect to join page render)
        second = client.post("/schools/classes/join", data={"code": code}, follow_redirects=True)
        assert second.status_code == 200
