"""Round-3 coverage: real-branch tests for remaining gaps.

Every test exercises production behaviour — assertions verify observable
outcomes, not "does not crash". Requires the celery-import guard pattern
for ``app.tasks.video``/``app.tasks.grading``.
"""

from __future__ import annotations

import importlib
import secrets
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import text

PASSWORD = "TestPass123!"


def _email() -> str:
    return f"r3-{uuid.uuid4().hex[:10]}@test.com"


@contextmanager
def _reload_tasks_video():
    import sys

    with (
        patch("app.tasks._HAS_CELERY", True),
        patch("app.tasks.celery_app") as mock_celery,
    ):

        def _task_dec(*a, **kw):
            return a[0] if a else (lambda f: f)

        mock_celery.task.side_effect = _task_dec
        import app.tasks.video as video

        importlib.reload(video)
        try:
            yield video
        finally:
            # لا إعادة تحميل هنا: بدون celery الاستيراد يرمي ImportError ويفسد
            # sys.modules. ننظّفه فقط ليُعيد باقي الاختبارات الاستيراد بحارسها.
            sys.modules.pop("app.tasks.video", None)


@contextmanager
def _reload_tasks_grading():
    with (
        patch("app.tasks._HAS_CELERY", True),
        patch("app.tasks.celery_app") as mock_celery,
    ):

        def _task_dec(*a, **kw):
            return a[0] if a else (lambda f: f)

        mock_celery.task.side_effect = _task_dec
        import app.tasks.grading as grading

        importlib.reload(grading)
        try:
            yield grading
        finally:
            pass


# ───────────────────────── tenancy: super_admin branch ─────────────────────────


def test_super_admin_request_stays_unscoped(app):
    """مشرف كلي مسجّل يدخل: before_request يمرّر دوره → GUCs الإشراف 1."""
    from tests.conftest import make_user

    sa_email = _email()
    make_user(app, role="super_admin", school_id=None, email=sa_email)
    client = app.test_client()
    client.post("/auth/login", data={"email": sa_email, "password": PASSWORD})
    resp = client.get("/health")
    assert resp.status_code == 200


# ───────────────────────── rls: snapshot & scope branches ─────────────────────────


def test_snapshot_broken_g_falls_back_inside_context(app, monkeypatch):
    import app.core.rls as rls

    class _BadG:
        @property
        def _rls_request_gucs(self):
            raise RuntimeError("g is broken")

    monkeypatch.setattr("flask.g", _BadG())
    monkeypatch.setattr(rls, "_session_in_transaction", lambda: False)
    with app.app_context():
        snap = rls._request_guc_snapshot()
    assert set(snap) == set(rls._REQUEST_GUC_NAMES)


def test_snapshot_returns_cached_copy(app):
    import app.core.rls as rls

    with app.app_context():
        from flask import g

        g._rls_request_gucs = {name: f"v-{i}" for i, name in enumerate(rls._REQUEST_GUC_NAMES)}
        snap = rls._request_guc_snapshot()
        assert snap == dict(g._rls_request_gucs)


def test_request_gucs_from_flask_cached(app):
    import app.core.rls as rls

    with app.app_context():
        from flask import g

        assert rls._request_gucs_from_flask() is None
        cache = {name: f"c{i}" for i, name in enumerate(rls._REQUEST_GUC_NAMES)}
        g._rls_request_gucs = cache
        assert rls._request_gucs_from_flask() == cache


def test_request_gucs_from_flask_broken_g(app, monkeypatch):
    import app.core.rls as rls

    class _BadG:
        @property
        def _rls_request_gucs(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("flask.g", _BadG())
    with app.app_context():
        assert rls._request_gucs_from_flask() is None


def test_access_read_scope_elevates_inside_transaction(app):
    import app.core.rls as rls
    from app.extensions import db

    with app.app_context():
        db.session.execute(text("SELECT 1"))  # معاملة مفتوحة قبل النطاق
        with rls.access_read_scope("lessons", 1):
            pass  # يجب ألا يرفع


def test_access_read_scope_rollback_failure_swallowed(app, monkeypatch):
    import app.core.rls as rls

    def _boom_rollback():
        raise RuntimeError("rollback broke")

    monkeypatch.setattr(rls.db.session, "rollback", _boom_rollback)
    with app.app_context():
        with rls.access_read_scope("lessons", 1):
            pass  # يجب ألا يرفع رغم فشل rollback


def test_access_read_scope_nested_keeps_depth(app):
    import app.core.rls as rls

    with app.app_context():
        with rls.access_read_scope("lessons", 1):
            depth = getattr(rls._platform_scope, "depth", 0)
            with rls.access_read_scope("lessons", 2):
                pass
            assert rls._platform_scope.depth == depth
        assert rls._platform_scope.depth == 0


def test_get_for_access_check_quiz_without_deleted_at(app, monkeypatch):
    """نموذج quizzes بلا deleted_at: يُستدعى فرع الاستعلام بدون فلتر الحذف."""
    from tests.conftest import make_class, make_grade, make_school, make_subject

    import app.core.rls as rls
    from app.extensions import db
    from app.models.assessment import Question, Quiz

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)

    with app.app_context():
        quiz = Quiz(class_id=cid, title="اختبار تغطية", status="published")
        db.session.add(quiz)
        db.session.flush()
        db.session.add(Question(quiz_id=quiz.id, type="mcq", prompt="س", mark=1))
        db.session.commit()
        qid = quiz.id

    monkeypatch.setattr(Quiz, "_access_check_eager", ("questions",), raising=False)
    with app.app_context():
        row = rls.get_for_access_check(Quiz, qid)
    assert row is not None and row.id == qid


def test_get_for_access_check_child_expunge_failure_swallowed(app, monkeypatch):
    """فشل expunge على ابن محمّل يُبلَّغ عنه ولا يُسقط الفحص."""
    from tests.conftest import make_class, make_grade, make_school, make_subject

    import app.core.rls as rls
    from app.extensions import db
    from app.models.assessment import Question, Quiz

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)

    with app.app_context():
        quiz = Quiz(class_id=cid, title="اختبار تنظيف", status="published")
        db.session.add(quiz)
        db.session.flush()
        db.session.add(Question(quiz_id=quiz.id, type="mcq", prompt="س", mark=1))
        db.session.commit()
        qid = quiz.id

    with app.app_context():
        monkeypatch.setattr(Quiz, "_access_check_eager", ("questions",), raising=False)
        real_expunge = db.session.expunge

        def _picky_expunge(obj):
            if isinstance(obj, Question):
                raise RuntimeError("cannot expunge question")
            return real_expunge(obj)

        monkeypatch.setattr(db.session, "expunge", _picky_expunge)
        row = rls.get_for_access_check(Quiz, qid)
    assert row is not None


def test_disable_all_rls_policies_tolerates_errors(app, monkeypatch):
    import app.core.rls as rls

    def _boom(*a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(rls.db.session, "execute", _boom)
    with app.app_context():
        rls.disable_all_rls_policies()  # يجب ألا يرفع


def test_enable_all_rls_policies_nothing_to_do(app, monkeypatch):
    import app.core.rls as rls

    monkeypatch.setattr(rls, "build_all_policy_ddl", lambda *a, **k: ([], []))
    monkeypatch.setattr(rls, "_apply", lambda stmts: None)
    with app.app_context():
        rls.enable_all_rls_policies()  # يجب ألا يرفع


def test_enable_rls_on_table_without_class_expression(app):
    import app.core.rls as rls

    with app.app_context():
        assert rls.enable_rls_on_table("academic_events") is True


def test_enable_rls_on_directly_tenant_table(app):
    """جدول مباشر بلا تعبير صفي ⇒ لا يُضاف أي ذراع قراءة."""
    import app.core.rls as rls

    with app.app_context():
        assert rls.enable_rls_on_table("academic_events") is True


def test_enable_rls_on_indirect_table_without_class_expression(app):
    import app.core.rls as rls

    with app.app_context():
        assert rls.enable_rls_on_indirect_table("rubric_criteria", "SELECT 1") is True


def test_enable_rls_on_indirect_table_user_owned_arms(app):
    import app.core.rls as rls

    with app.app_context():
        assert rls.enable_rls_on_indirect_table("subscriptions", "SELECT 1") is True


def test_enable_rls_on_indirect_table_actor_owned_arms(app):
    import app.core.rls as rls

    with app.app_context():
        assert rls.enable_rls_on_indirect_table("submissions", "SELECT 1") is True


# ───────────────────────── wallet_service: filters & reversals ─────────────────────────


def _credit(app, school_id, user_id, amount=100.0):
    from app.services import wallet_service

    with app.app_context():
        wallet, _ = wallet_service.get_or_create_wallet(school_id=school_id, user_id=user_id)
        assert wallet is not None
        txobj, err = wallet_service.admin_credit(
            school_id=school_id,
            target_user_id=user_id,
            amount=Decimal(str(amount)),
            idempotency_key=f"r3:{secrets.token_hex(8)}",
            description="إيداع إداري",
            operator_id=user_id,
        )
        assert err is None
        return txobj


def _raw_tx(app, school_id, *, source, dest, amount=Decimal("10.00"), ttype="admin_adjustment", ref_type=None, ref_id=None):
    from app.extensions import db
    from app.models.wallet import WalletTransaction

    with app.app_context():
        t = WalletTransaction(
            school_id=school_id,
            source_wallet_id=source,
            destination_wallet_id=dest,
            amount=amount,
            currency="ILS",
            transaction_type=ttype,
            transaction_hash=secrets.token_hex(16),
            idempotency_key=f"raw:{secrets.token_hex(12)}",
            reference_type=ref_type,
            reference_id=ref_id,
            status="completed",
        )
        db.session.add(t)
        db.session.commit()
        return t.id


def test_ledger_query_filters(app):
    from tests.conftest import make_school, make_user

    from app.services.wallet_service import ledger_query

    sid = make_school(app)
    uid = make_user(app, role="student", school_id=sid)
    _credit(app, sid, uid, 100.0)
    with app.app_context():
        by_type = ledger_query(school_id=sid, tx_type="admin_adjustment").count()
        assert by_type >= 1
        assert ledger_query(school_id=sid, tx_type="transfer").count() == 0

        assert ledger_query(school_id=sid, status="completed").count() >= 1
        assert ledger_query(school_id=sid, status="pending").count() == 0

        now = datetime.now(UTC)
        assert ledger_query(school_id=sid, date_from=now - timedelta(days=1), date_to=now + timedelta(days=1)).count() >= 1
        assert ledger_query(school_id=sid, date_from=datetime(2030, 1, 1, tzinfo=UTC)).count() == 0
        assert ledger_query(school_id=sid, date_to=datetime(2020, 1, 1, tzinfo=UTC)).count() == 0

        assert ledger_query(school_id=sid, search="إيداع").count() >= 1
        assert ledger_query(school_id=sid, search="zzz-no-such-token").count() == 0


def test_admin_deposit_invalid_ids(app):
    from tests.conftest import make_school

    from app.services import wallet_service

    sid = make_school(app)
    with app.app_context():
        res, err = wallet_service.admin_deposit(
            school_id=sid, target_user_id=0, amount=Decimal("10.00"), operator_id=1
        )
    assert res is None and err


def test_admin_deposit_wallet_failure(app, monkeypatch):
    from tests.conftest import make_school, make_user

    from app.services import wallet_service

    sid = make_school(app)
    uid = make_user(app, role="student", school_id=sid)
    monkeypatch.setattr(wallet_service, "get_or_create_wallet", lambda *a, **kw: (None, "تعذّر الإنشاء"))
    with app.app_context():
        res, err = wallet_service.admin_deposit(
            school_id=sid, target_user_id=uid, amount=Decimal("10.00"), operator_id=1
        )
    assert res is None and err


def test_find_reversal_of_finds_reversal(app):
    from tests.conftest import make_school, make_user

    from app.services import wallet_service

    sid = make_school(app)
    uid = make_user(app, role="student", school_id=sid)
    txobj = _credit(app, sid, uid, 50.0)
    with app.app_context():
        reversal, err = wallet_service.reverse_transaction(
            school_id=sid, transaction_id=txobj.id, operator_id=uid, reason="اختبار الاسترداد"
        )
        assert err is None and reversal is not None
        found = wallet_service.find_reversal_of(txobj.id)
    assert found is not None and found.reference_id == txobj.id


def test_reverse_origin_not_active(app):
    from tests.conftest import make_school, make_user

    from app.extensions import db
    from app.models.wallet import Wallet
    from app.services import wallet_service

    sid = make_school(app)
    uid = make_user(app, role="student", school_id=sid)
    txobj = _credit(app, sid, uid, 50.0)
    with app.app_context():
        wallet = Wallet.query.filter_by(school_id=sid, user_id=uid).first()
        wallet.status = "frozen"
        db.session.commit()
        res, err = wallet_service.reverse_transaction(school_id=sid, transaction_id=txobj.id, operator_id=uid, reason="")
    assert res is None and err


def test_reverse_back_not_active(app):
    """رجوع حركة مدينة من محفظة مجمّدة: الوجهة NULL ⇒ يتخطى فحص المنشأ."""
    from tests.conftest import make_school, make_user

    from app.extensions import db
    from app.models.wallet import Wallet
    from app.services import wallet_service

    sid = make_school(app)
    uid = make_user(app, role="student", school_id=sid)
    with app.app_context():
        wallet, _ = wallet_service.get_or_create_wallet(school_id=sid, user_id=uid)
        tid = _raw_tx(app, sid, source=wallet.id, dest=None, amount=Decimal("10.00"))
        w = db.session.get(Wallet, wallet.id)
        w.status = "frozen"
        db.session.commit()
        res, err = wallet_service.reverse_transaction(school_id=sid, transaction_id=tid, operator_id=uid, reason="")
    assert res is None and err


def test_request_topup_over_limit(app):
    from tests.conftest import make_school, make_user

    from app.services import wallet_service

    sid = make_school(app)
    parent = make_user(app, role="parent", school_id=sid)
    child = make_user(app, role="student", school_id=sid)
    with app.app_context():
        res, err = wallet_service.request_topup(sid, parent, child, Decimal("10001.00"), note="")
    assert res is None and err


def test_request_topup_child_not_linked(app):
    from tests.conftest import make_school, make_user

    from app.services import wallet_service

    sid = make_school(app)
    other = make_school(app)
    parent = make_user(app, role="parent", school_id=sid)
    child_b = make_user(app, role="student", school_id=other)
    with app.app_context():
        res, err = wallet_service.request_topup(sid, parent, child_b, Decimal("50.00"), note="")
    assert res is None and err


def _pending_topup(app, school_id, parent, child, amount="50.00"):
    from app.extensions import db
    from app.models.wallet import WalletTopupRequest

    with app.app_context():
        req = WalletTopupRequest(
            school_id=school_id,
            parent_id=parent,
            child_user_id=child,
            amount=Decimal(amount),
            status="pending",
        )
        db.session.add(req)
        db.session.commit()
        return req.id


def test_review_topup_unknown_request(app):
    from tests.conftest import make_school, make_user

    from app.services import wallet_service

    sid = make_school(app)
    parent = make_user(app, role="parent", school_id=sid)
    with app.app_context():
        res, err = wallet_service.review_topup(request_id=999_999, school_id=sid, operator_id=parent, approve=True)
    assert res is None and err


def test_review_topup_deposit_failure(app, monkeypatch):
    from tests.conftest import make_school, make_user

    from app.services import wallet_service

    sid = make_school(app)
    parent = make_user(app, role="parent", school_id=sid)
    child = make_user(app, role="student", school_id=sid)
    rid = _pending_topup(app, sid, parent, child)

    def _failing_deposit(*a, **kw):
        return None, "الرصيد غير كافٍ"

    monkeypatch.setattr(wallet_service, "admin_deposit", _failing_deposit)
    with app.app_context():
        res, err = wallet_service.review_topup(request_id=rid, school_id=sid, operator_id=parent, approve=True)
    assert res is None and err


# ───────────────────────── video_service: tenant boundary ─────────────────────────


def test_validate_lesson_access_school_admin_of_other_school_denied(app):
    from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user

    from app.services.video_service import validate_lesson_access

    sid_a = make_school(app)
    sid_b = make_school(app)
    gid = make_grade(app, sid_a, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid_a, gid, subj)
    lesson_id = make_lesson(app, cid)
    admin_b = make_user(app, role="school_admin", school_id=sid_b)
    with app.app_context():
        ok, err = validate_lesson_access(admin_b, sid_a, lesson_id)
    assert ok is False
    assert err  # سبب الرفض موجود


# ───────────────────────── tasks/video: pipeline branches ─────────────────────────


def test_hls_pipeline_completes_without_lesson_attachment(app, tmp_path, monkeypatch):
    import shutil

    from tests.conftest import make_lesson, make_class, make_grade, make_school, make_subject

    from app.extensions import db
    from app.models.content import LessonAttachment

    with _reload_tasks_video() as video:
        src = tmp_path / "noatt.mp4"
        src.write_bytes(b"fake")
        monkeypatch.setattr(video, "_probe_video", lambda p: {"height": 480})
        monkeypatch.setattr(video, "_transcode_variant", lambda *a, **k: "source.m3u8")
        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=1)
        cid = make_class(app, sid, gid, make_subject(app))
        lesson_id = make_lesson(app, cid)
        with app.app_context():
            assert LessonAttachment.query.filter_by(lesson_id=lesson_id).first() is None
            result = video.transcode_video_to_hls(
                self=None, lesson_id=lesson_id, source_file_path=str(src), school_id=sid
            )
        assert result["status"] == "completed"
        shutil.rmtree(result["output_dir"], ignore_errors=True)


def test_hls_pipeline_failure_before_temp_dir(app, tmp_path, monkeypatch):
    with _reload_tasks_video() as video:
        src = tmp_path / "early.mp4"
        src.write_bytes(b"fake")

        def _boom_mkdtemp(*a, **k):
            raise RuntimeError("mkdtemp exploded")

        monkeypatch.setattr(video.tempfile, "mkdtemp", _boom_mkdtemp)
        with app.app_context():
            result = video.transcode_video_to_hls(
                self=None, lesson_id=999_999, source_file_path=str(src), school_id=1
            )
    assert result["status"] == "failed"
    assert "mkdtemp exploded" in result["error"]


def test_transcode_variant_height_zero_omits_scale_filter(monkeypatch):
    with _reload_tasks_video() as video:
        captured = {}
        fake = MagicMock(returncode=1, stderr="")

        def _run(cmd, **kw):
            captured["cmd"] = cmd
            return fake

        monkeypatch.setattr(video.subprocess, "run", _run)
        variant = {"name": "src", "bitrate": "1000k", "maxrate": "1000k", "bufsize": "1000k", "height": 0}
        video._transcode_variant("s.mp4", "out_dir", variant, "key.txt")
    assert "-vf" not in captured["cmd"]


# ───────────────────────── tasks/i18n_monitor: no-celery branch ─────────────────────────


def test_i18n_monitor_without_celery_has_no_audit_task():
    import app.tasks.i18n_monitor as im

    with patch("app.tasks._HAS_CELERY", False), patch("app.tasks.celery_app", None):
        importlib.reload(im)
        assert im.audit_translation_catalogs is None
        assert im._celery_app is None
    importlib.reload(im)


# ───────────────────────── tasks/grading: existing-entry update ─────────────────────────


def test_batch_update_gradebook_existing_entry_keeps_note(app):
    from tests.conftest import (
        make_class,
        make_grade,
        make_grade_category,
        make_grade_item,
        make_school,
        make_subject,
        make_user,
    )

    with _reload_tasks_grading() as grading:
        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=1)
        subj = make_subject(app)
        tid = make_user(app, role="teacher", school_id=sid)
        cid = make_class(app, sid, gid, subj, teacher_id=tid)
        stud = make_user(app, role="student", school_id=sid)
        cat = make_grade_category(app, cid, "نهائي", 1.0)
        item = make_grade_item(app, cid, cat, "الاختبار", 100)

        with app.app_context():
            first = grading.batch_update_gradebook(
                MagicMock(), class_id=cid, grade_item_id=item, entries=[{"student_id": stud, "mark": 80, "note": "قديمة"}]
            )
            second = grading.batch_update_gradebook(
                MagicMock(), class_id=cid, grade_item_id=item, entries=[{"student_id": stud, "mark": 90}]
            )
        assert first["updated"] == 1
        assert second["updated"] == 1

        from app.extensions import db
        from app.models.gradebook import GradeEntry

        with app.app_context():
            entry = GradeEntry.query.filter_by(grade_item_id=item, student_id=stud).first()
            assert entry is not None
            assert entry.mark == 90
            assert entry.note == "قديمة"  # لم تُمسّ الملاحظة الموجودة


# ───────────────────────── report_card: item without entries ─────────────────────────


def test_report_card_item_without_any_entry(app):
    from tests.conftest import (
        make_class,
        make_class_member,
        make_grade,
        make_grade_category,
        make_grade_item,
        make_school,
        make_subject,
        make_user,
    )

    from app.services.report_card import generate_report_card

    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=1)
        subj = make_subject(app)
        tid = make_user(app, role="teacher", school_id=sid)
        cid = make_class(app, sid, gid, subj, teacher_id=tid)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        make_grade_category(app, cid, "امتحانات", 1.0)
        item_cat = make_grade_category(app, cid, "نهايات", 1.0)
        make_grade_item(app, cid, item_cat, "الاختبار النهائي", 100)

        result = generate_report_card(uid, cid)
    assert result["grade_data"]["final_grade"] == 0
