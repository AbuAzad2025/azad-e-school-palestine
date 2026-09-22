"""تغطية جراحية للفجوات المحددة في تقرير CI (Round M2).

المسارات المستهدفة (من تقرير التغطية الأخير):
- services/ai.py: 30, 155, 160-164, 181, 493, 517-518
- services/base.py: 63, 81, 114, 149, 151, 163-164
- services/billing.py: 140-141, 422, 430, 433, 439-440
- services/assessment.py: 107-112, 125
- services/quiz_ai_service.py: 151-155, 286
- services/payments.py: 535, 537-539, 555
- services/school_approvals.py: 51, 99, 106, 146
- tasks/grading.py: 238-243
- routes: family 31-32/54-55, schools 29-32, tutoring 52/137-138/341,
  admin 39-42/314/341-342/474, ai 29/77-78, assessment 170-171/510
"""

from __future__ import annotations

import asyncio
import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_lesson,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutor_profile,
    make_tutoring_session,
    make_user,
)
from werkzeug.exceptions import Forbidden, NotFound

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _self():
    """Dummy bound-task self لـbind=True (retry لا يُستدعى هنا)."""
    m = MagicMock()
    m.retry.side_effect = RuntimeError("retry-should-not-fire")
    return m


@pytest.fixture()
def celery_guard():
    """استيراد وحدات المهام مع رقعة حارس Celery (البيئة المحلية بلا celery)."""
    with patch("app.tasks._HAS_CELERY", True):
        mock_celery = MagicMock()

        def _task_dec(*a, **kw):
            if a:
                return a[0]
            return lambda f: f

        mock_celery.task.side_effect = _task_dec
        with patch("app.tasks.celery_app", mock_celery):
            from app.tasks import grading  # noqa: F401

            yield


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def _uid() -> str:
    from tests.conftest import _uid as _u

    return _u()


def mk_user(app, role: str, school_id=None, approved=True):
    email = f"m2-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, approved=approved, email=email)
    return uid, email


def login_as(app, uid_email):
    client = app.test_client()
    client.post("/auth/login", data={"email": uid_email[1], "password": PASSWORD})
    return client


def _setup_class(app, teacher_id=None):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj, teacher_id=teacher_id)
    return sid, cid


async def _collect(agen):
    return [c async for c in agen]


# ═══════════════════════════════════════════════════════════════════════
# services/ai.py — 30, 155, 160-164, 181, 493, 517-518
# ═══════════════════════════════════════════════════════════════════════


class TestAiServiceGaps:
    def test_placeholder_client_when_openai_missing(self, app):
        """سطر 30: كلاس AsyncOpenAI البديل عند غياب openai (فرع ImportError)."""
        import importlib.util
        import sys

        import app.services.ai as ai_mod

        saved = sys.modules.get("openai")
        sys.modules["openai"] = None  # يجعل from openai import ... يرفع ImportError
        try:
            spec = importlib.util.spec_from_file_location("ai_fallback_probe_m2", ai_mod.__file__)
            probe = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(probe)
        finally:
            if saved is None:
                sys.modules.pop("openai", None)
            else:
                sys.modules["openai"] = saved

        assert probe.OPENAI_AVAILABLE is False
        inst = probe.AsyncOpenAI()
        assert isinstance(inst, probe.AsyncOpenAI)

    def test_init_builds_client_when_key_present(self, app):
        """سطر 155: __init__ يبني AsyncOpenAI عند توفر المفتاح."""
        from app.services import ai as ai_mod
        from app.services.ai import AiService

        original = AiService._client
        try:
            AiService._client = None
            fake = MagicMock()
            with (
                patch.object(ai_mod, "OPENAI_AVAILABLE", True),
                patch.object(ai_mod, "AsyncOpenAI", return_value=fake),
                # AiConfig يقرأ البيئة عند الاستيراد — نرقع الصنف ذاته
                patch.object(ai_mod, "AiConfig", return_value=MagicMock(api_key="sk-init-test")),
            ):
                AiService()
                assert AiService._client is fake
        finally:
            AiService._client = original

    def test_get_client_without_library_raises(self, app):
        """سطر 159: غياب مكتبة openai يرفع RuntimeError موجَّهاً."""
        from app.services import ai as ai_mod
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            with patch.object(ai_mod, "OPENAI_AVAILABLE", False):
                with pytest.raises(RuntimeError, match="OpenAI library not installed"):
                    svc._get_client()

    def test_get_client_no_key_raises(self, app):
        """أسطر 155/160-164: _get_client بلا مفتاح API يرفع RuntimeError."""
        from app.services import ai as ai_mod
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            original = AiService._client
            try:
                AiService._client = None
                with patch.object(ai_mod, "OPENAI_AVAILABLE", True), patch.object(svc.config, "api_key", ""):
                    with pytest.raises(RuntimeError, match="AI_API_KEY"):
                        svc._get_client()
            finally:
                AiService._client = original

    def test_get_client_builds_when_available(self, app):
        """بناء العميل عند توفر المكتبة والمفتاح."""
        from app.services import ai as ai_mod
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            original = AiService._client
            try:
                AiService._client = None
                fake = MagicMock()
                with (
                    patch.object(ai_mod, "OPENAI_AVAILABLE", True),
                    patch.object(ai_mod, "AsyncOpenAI", return_value=fake),
                    patch.object(svc.config, "api_key", "sk-test"),
                ):
                    assert svc._get_client() is fake
            finally:
                AiService._client = original

    def test_check_limits_all_arms(self, app):
        """أسطر 149-159/181: كل أذرع _check_limits (بلا محدد/بلا ميزانية/تجاوز)."""
        from app.services.ai import AiService, BudgetTracker, RateLimiter

        with app.app_context():
            svc = AiService()
            o_r, o_b = AiService._rate_limiter, AiService._budget_tracker
            try:
                # لا محدد معدل ولا ميزانية → مسموح
                AiService._rate_limiter = None
                AiService._budget_tracker = None
                assert svc._check_limits(100) == (True, "")

                # محدد نشط + ميزانية غائبة → يُسمح (فرع return True الأوسط)
                AiService._rate_limiter = RateLimiter(60, 100_000)
                assert svc._check_limits(100) == (True, "")

                # تجاوز معدل الطلبات
                AiService._rate_limiter = RateLimiter(0, 100_000)
                ok, msg = svc._check_limits(100)
                assert ok is False and msg.startswith("Rate limit:")

                # تجاوز الميزانية
                AiService._rate_limiter = RateLimiter(60, 100_000)
                AiService._budget_tracker = BudgetTracker(0.0)
                ok, msg = svc._check_limits(100)
                assert ok is False and msg.startswith("Budget:")
            finally:
                AiService._rate_limiter, AiService._budget_tracker = o_r, o_b

    def test_real_stream_error_yields_sse_error(self, app):
        """سطر 493: استثناء من _real_stream أثناء البث → SSE خطأ ثم [DONE]."""
        from app.services import ai as ai_mod
        from app.services.ai import AiService

        sid, _ = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)

        async def _boom(messages, session_id):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        with app.app_context():
            svc = AiService()
            with (
                patch.object(ai_mod, "OPENAI_AVAILABLE", True),
                patch.object(svc.config, "api_key", "sk-test"),
                patch.object(svc, "_real_stream", _boom),
            ):
                chunks = asyncio.run(_collect(svc.ask_question_stream(uid, "سؤال")))

        assert any('"error"' in c for c in chunks)
        assert chunks[-1] == "data: [DONE]\n\n"

    def test_real_stream_passes_chunks_through(self, app):
        """سطر 493: تمرير أجزاء البث الحقيقي كما هي."""
        from app.services import ai as ai_mod
        from app.services.ai import AiService

        sid, _ = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)

        async def _ok_stream(messages, session_id):
            yield 'data: {"delta": "أ"}\n\n'
            yield "data: [DONE]\n\n"

        with app.app_context():
            svc = AiService()
            with (
                patch.object(ai_mod, "OPENAI_AVAILABLE", True),
                patch.object(svc.config, "api_key", "sk-test"),
                patch.object(svc, "_real_stream", _ok_stream),
            ):
                chunks = asyncio.run(_collect(svc.ask_question_stream(uid, "سؤال")))

        assert chunks[0] == 'data: {"delta": "أ"}\n\n'
        assert chunks[-1] == "data: [DONE]\n\n"

    def test_ask_question_non_streaming_parses_sse(self, app):
        """أسطر 517-518: تجميع deltas مع تخطي أجزاء SSE غير الصالحة."""
        from app.services.ai import AiService

        sid, _ = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)

        async def _stream(user_id, question, context, class_id, lesson_id):
            yield 'data: {"delta": "مرحبا"}\n\n'
            yield "data: not-json\n\n"  # فرع JSONDecodeError → debug log
            yield 'data: {"other": 1}\n\n'  # بلا delta → يتخطى
            yield "data: [DONE]\n\n"

        with app.app_context():
            svc = AiService()
            with patch.object(svc, "ask_question_stream", _stream):
                result = asyncio.run(svc.ask_question(uid, "سؤال"))

        assert result["answer"] == "مرحبا"
        assert result["question"] == "سؤال"


# ═══════════════════════════════════════════════════════════════════════
# services/base.py — 63, 81, 114, 149, 151, 163-164
# ═══════════════════════════════════════════════════════════════════════


class TestBaseServiceGaps:
    def test_query_without_model_raises(self, app):
        """سطر 63: _query بلا model يرفع TxError."""
        from app.core.db import TxError
        from app.services.base import BaseService

        class Svc(BaseService):
            model = None

        with pytest.raises(TxError, match="model غير محدد"):
            Svc._query()

    def test_get_or_404_aborts_404(self, app):
        """سطر 81: get_or_404 يستدعي abort(404) عند عدم الوجود."""
        from app.models.user import User
        from app.services.base import BaseService

        class Svc(BaseService):
            model = User

        with app.app_context():
            with pytest.raises(NotFound):
                Svc.get_or_404(987654321)

    def test_create_without_model_raises(self, app):
        """سطر 114: create بلا model يرفع TxError."""
        from app.core.db import TxError
        from app.services.base import BaseService

        class Svc(BaseService):
            model = None

        with pytest.raises(TxError, match="model غير محدد"):
            Svc.create(name="x")

    def test_delete_missing_returns_false(self, app):
        """سطر 149: حذف كيان غير موجود يعيد False."""
        from app.models.user import User
        from app.services.base import BaseService

        class Svc(BaseService):
            model = User

        with app.app_context():
            assert Svc.delete(987654321) is False

    def test_delete_soft_for_softdelete_models(self, app):
        """سطر 151: نموذج بـ deleted_at (ClassRoom) → حذف ناعم."""
        from app.extensions import db
        from app.models.class_room import ClassRoom
        from app.services.base import BaseService

        class Svc(BaseService):
            model = ClassRoom

        sid, cid = _setup_class(app)
        with app.app_context():
            assert Svc.delete(cid) is True
            room = db.session.get(ClassRoom, cid)
            assert room is not None
            assert room.deleted_at is not None

    def test_get_and_count_success_arms(self, app):
        """أسطر 64/70/81/161-165: الأذرع الناجحة لget/_query/get_or_404/count."""
        from app.models.school import Subject
        from app.services.base import BaseService

        class Svc(BaseService):
            model = Subject

        subj_id = make_subject(app)
        with app.app_context():
            assert Svc.get(subj_id) is not None
            assert Svc.get_or_404(subj_id).id == subj_id
            q = Svc._query()
            assert q.count() >= 1
            assert Svc.count() >= 1
            assert Svc.count(name_ar="غير-موجود-xyz") == 0
            # فلتر على عمود غير موجود يُتجاهل بهدوء
            assert Svc.count(nonexistent_col=5) >= 1

    def test_delete_hard_for_plain_models(self, app):
        """أسطر 163-164: نموذج بلا deleted_at (Subject) → حذف فيزيائي."""
        from app.extensions import db
        from app.models.school import Subject
        from app.services.base import BaseService

        class Svc(BaseService):
            model = Subject

        subj_id = make_subject(app)
        with app.app_context():
            assert Svc.delete(subj_id) is True
            assert db.session.get(Subject, subj_id) is None


# ═══════════════════════════════════════════════════════════════════════
# services/billing.py — 140-141, 422, 430, 433, 439-440
# ═══════════════════════════════════════════════════════════════════════


class TestBillingGaps:
    def _plan_and_sub(self, app):
        sid, cid = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        pid = make_subscription_plan(app, sid, cid)
        sub_id = make_subscription(app, uid, pid, cid)
        return sid, sub_id

    def test_record_manual_payment_with_receipt(self, app):
        """أسطر 140-141: حفظ ملف إيصال حقيقي عبر save_upload."""
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription
        from app.services.billing import record_manual_payment
        from werkzeug.datastructures import FileStorage

        _, sub_id = self._plan_and_sub(app)
        with app.app_context():
            sub = db.session.get(Subscription, sub_id)
            fs = FileStorage(
                stream=io.BytesIO(b"%PDF-1.4 fake receipt"), filename="receipt.pdf", content_type="application/pdf"
            )
            payment, err = record_manual_payment(sub, "REF-RC-1", 100, receipt_file=fs)
            assert err is None
            assert payment is not None
            row = db.session.get(ManualPayment, payment.id)
            assert len(row.receipts) >= 1

    def test_record_manual_payment_rejects_bad_file(self, app):
        """أسطر 140-141: فشل save_upload بـTxError → (None, رسالة)."""
        from app.services.billing import record_manual_payment
        from werkzeug.datastructures import FileStorage

        _, sub_id = self._plan_and_sub(app)
        with app.app_context():
            from app.extensions import db
            from app.models.billing import Subscription

            sub = db.session.get(Subscription, sub_id)
            # ملف بلا امتداد مسموح → save_upload يرفع TxError
            bad = FileStorage(stream=io.BytesIO(b"MZ"), filename="evil.exe", content_type="application/octet-stream")
            payment, err = record_manual_payment(sub, "REF-BAD", 100, receipt_file=bad)
            assert payment is None
            assert err

    def test_apply_discount_guards(self, app):
        """أسطر 410/414/418: حراس كود فارغ/اشتراك مفقود/خطأ تحقق."""
        from app.services import billing as bmod
        from app.services.billing import apply_discount_code

        _, sub_id = self._plan_and_sub(app)
        with app.app_context():
            assert apply_discount_code(sub_id, "   ") == (None, "كود الخصم مطلوب.")
            result, err = apply_discount_code(987654321, "ANY")
            assert result is None and "الاشتراك غير موجود" in err
            with patch.object(bmod, "validate_discount_code", return_value=(None, "كود غير صالح")):
                result, err = apply_discount_code(sub_id, "ANY")
            assert result is None and err == "كود غير صالح"

    def test_apply_discount_defensive_none(self, app):
        """سطر 422: تحقق عابر لخصم None (عقد داخلي) → ValueError."""
        from app.services import billing as bmod
        from app.services.billing import apply_discount_code

        _, sub_id = self._plan_and_sub(app)
        with app.app_context(), patch.object(bmod, "validate_discount_code", return_value=(None, None)):
            with pytest.raises(ValueError, match="Discount cannot be None"):
                apply_discount_code(sub_id, "ANYCODE")

    def test_apply_discount_exhausted_race(self, app):
        """أسطر 430/439-440: استنفاد بين التحقق والتطبيق → rowcount 0 → TxError."""
        from app.extensions import db
        from app.models.billing import DiscountCode
        from app.services import billing as bmod
        from app.services.billing import apply_discount_code

        _, sub_id = self._plan_and_sub(app)
        with app.app_context():
            db.session.add(
                DiscountCode(code="M2EXH", name="عرض", type="fixed", value=Decimal("10"), max_uses=1, used_count=1)
            )
            db.session.commit()
            # نحاكي السباق: التحقق يمر لكن الصف استُنفد فعلاً
            with app.app_context(), patch.object(bmod, "validate_discount_code", return_value=(Decimal("10"), None)):
                result, err = apply_discount_code(sub_id, "M2EXH")
            assert result is None
            assert "استنفاد" in err

    def test_apply_discount_exceeds_price(self, app):
        """أسطر 433/439-440: خصم أكبر من سعر الاشتراك نفسه → TxError."""
        from app.extensions import db
        from app.models.billing import DiscountCode
        from app.services.billing import apply_discount_code

        sid, cid = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        pid = make_subscription_plan(app, sid, cid)  # سعر الخطة 100 — سقف الخصم
        sub_id = make_subscription(app, uid, pid, cid, price=50.0)  # سعر الاشتراك أقل
        with app.app_context():
            db.session.add(
                DiscountCode(code="M2BIG", name="عرض", type="fixed", value=Decimal("99999"), max_uses=5, used_count=0)
            )
            db.session.commit()
            result, err = apply_discount_code(sub_id, "M2BIG")
            assert result is None
            assert err is not None and err.endswith("سعر الاشتراك.")

    def test_apply_discount_success_reduces_price(self, app):
        """سطر 436: تطبيق ناجح يخفض السعر ويزيد used_count."""
        from app.extensions import db
        from app.models.billing import DiscountCode, Subscription
        from app.services.billing import apply_discount_code

        _, sub_id = self._plan_and_sub(app)
        with app.app_context():
            db.session.add(
                DiscountCode(code="M2OK", name="عرض", type="fixed", value=Decimal("20"), max_uses=5, used_count=0)
            )
            db.session.commit()
            original = db.session.get(Subscription, sub_id).price
            discount, err = apply_discount_code(sub_id, "M2OK")
            assert err is None
            assert discount == Decimal("20")
            sub = db.session.get(Subscription, sub_id)
            assert sub.price == original - Decimal("20")
            assert (
                db.session.scalar(
                    __import__("sqlalchemy", fromlist=["select"])
                    .select(__import__("app.models.billing", fromlist=["DiscountCode"]).DiscountCode.used_count)
                    .where(__import__("app.models.billing", fromlist=["DiscountCode"]).DiscountCode.code == "M2OK")
                )
                == 1
            )


# ═══════════════════════════════════════════════════════════════════════
# services/assessment.py — 107-112 (سباق المحاولات), 125 (إعادة الرفع)
# ═══════════════════════════════════════════════════════════════════════


class TestAssessmentServiceGaps:
    def _mk_quiz(self, app, cid, uid, attempts=3):
        from app.extensions import db
        from app.models.assessment import Quiz

        quiz = Quiz(class_id=cid, title="race", attempts_allowed=attempts, created_by=uid)
        db.session.add(quiz)
        db.session.commit()
        return quiz

    def test_start_attempt_returns_in_progress(self, app):
        """أسطر 87-89: محاولة جارية قائمة → تُعاد مباشرة."""
        from app.services.assessment import start_attempt

        sid, cid = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            quiz = self._mk_quiz(app, cid, uid)
            att1, err1 = start_attempt(quiz, uid)
            assert err1 is None and att1 is not None
            att2, err2 = start_attempt(quiz, uid)
            assert err2 is None and att2.id == att1.id

    def test_start_attempt_race_returns_existing(self, app):
        """أسطر 107-112: IntegrityError أثناء tx → إعادة المحاولة الجارية المُدرجة."""
        from app.extensions import db
        from app.models.assessment import QuizAttempt
        from app.services import assessment as amod
        from app.services.assessment import start_attempt
        from sqlalchemy.exc import IntegrityError

        sid, cid = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            quiz = self._mk_quiz(app, cid, uid)

            def _race_then_insert(fn):
                # يحاكي: خصم متزامن أدخل الصف قبله مباشرة
                db.session.add(QuizAttempt(quiz_id=quiz.id, student_id=uid, status="in_progress"))
                raise IntegrityError("stmt", None, Exception("uq partial"))

            with patch.object(amod, "tx", _race_then_insert):
                att, err = start_attempt(quiz, uid)
            assert err is None
            assert att is not None and att.status == "in_progress"

    def test_start_attempt_race_without_existing_reraises(self, app):
        """سطر 125: سباق بلا محاولة قائمة → إعادة رفع الخطأ."""
        from app.services import assessment as amod
        from app.services.assessment import start_attempt
        from sqlalchemy.exc import IntegrityError

        sid, cid = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            quiz = self._mk_quiz(app, cid, uid)

            def _boom(fn):
                raise IntegrityError("stmt", None, Exception("uq partial"))

            with patch.object(amod, "tx", _boom):
                with pytest.raises(IntegrityError):
                    start_attempt(quiz, uid)

    def test_deadline_exceeded_naive_started_at(self, app):
        """أسطر 124-127: naive → UTC، وبلا مدة/بلا بداية → False."""
        from app.services.assessment import deadline_exceeded

        att = MagicMock()
        att.quiz = MagicMock(duration_min=30)
        att.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=61)
        att2 = MagicMock()
        att2.quiz = MagicMock(duration_min=30)
        att2.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        att3 = MagicMock()
        att3.quiz = MagicMock(duration_min=None)  # بلا مدة → False مبكراً
        att4 = MagicMock()
        att4.quiz = MagicMock(duration_min=30)
        att4.started_at = datetime.now(UTC) - timedelta(minutes=61)  # aware → يتخطى replace
        with app.app_context():
            assert deadline_exceeded(att) is True
            assert deadline_exceeded(att2) is False
            assert deadline_exceeded(att3) is False
            assert deadline_exceeded(att4) is True


# ═══════════════════════════════════════════════════════════════════════
# services/quiz_ai_service.py — 151-155, 286
# ═══════════════════════════════════════════════════════════════════════


_QUESTIONS = [
    {"question_text": "س1؟", "type": "mcq", "options": ["أ", "ب"], "correct_answer": "أ", "mark": 5},
    {"question_text": "س2؟", "type": "true_false", "options": [], "correct_answer": "صح", "mark": 2},
]


class TestQuizAiGaps:
    def test_generate_llm_error_returns_message(self, app):
        """فشل LLM يعيد رسالة واضحة (مسار يقود إلى أذرع الحفظ)."""
        from app.services import quiz_ai_service as qmod
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        lid = make_lesson(app, cid)

        with app.app_context():
            with (
                patch.object(qmod, "_extract_lesson_text", return_value="نص"),
                patch.object(qmod, "_call_llm", side_effect=RuntimeError("api down")),
            ):
                quiz, err = generate_quiz_from_lesson(lid, created_by=tid)
                assert quiz is None
                assert "LLM API error" in err

    def test_generate_tx_error_returns_message(self, app):
        """أسطر 151-152: TxError أثناء الحفظ الذري → (None, رسالة)."""
        from app.core.db import TxError
        from app.services import quiz_ai_service as qmod
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        lid = make_lesson(app, cid)

        with app.app_context():
            with (
                patch.object(qmod, "_extract_lesson_text", return_value="نص"),
                patch.object(qmod, "_call_llm", return_value=json.dumps(_QUESTIONS)),
                patch.object(qmod, "tx", side_effect=TxError("db boom")),
            ):
                quiz, err = generate_quiz_from_lesson(lid, created_by=tid)
                assert quiz is None
                assert err == "db boom"

    def test_generate_unexpected_db_error_returns_message(self, app):
        """أسطر 154-155: استثناء غير متوقع أثناء الحفظ → 'Database error: ...'."""
        from app.services import quiz_ai_service as qmod
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        lid = make_lesson(app, cid)

        with app.app_context():
            with (
                patch.object(qmod, "_extract_lesson_text", return_value="نص"),
                patch.object(qmod, "_call_llm", return_value=json.dumps(_QUESTIONS)),
                patch.object(qmod, "tx", side_effect=RuntimeError("conn reset")),
            ):
                quiz, err = generate_quiz_from_lesson(lid, created_by=tid)
                assert quiz is None
                assert err is not None and err.startswith("Database error")

    def test_parse_llm_response_embedded_json_array(self, app):
        """سطر 286: استخراج مصفوفة JSON مضمّنة، وNone عند غياب أي JSON."""
        from app.services.quiz_ai_service import _parse_llm_response

        raw = 'اقتراحات:\n```json\n[{"question_text": "س1"}, {"question_text": "س2"}]\n```\nوشكراً'
        result = _parse_llm_response(raw)
        assert result is not None
        assert len(result) == 2
        assert all("question_text" in q for q in result)

        assert _parse_llm_response("لا يوجد شيء هنا") is None
        # مصفوفة غير صالحة داخل نص → المحاولة الثانية تفشل → None
        assert _parse_llm_response("قبل [ليس-json] بعد") is None


# ═══════════════════════════════════════════════════════════════════════
# services/payments.py — 535, 537-539, 555
# ═══════════════════════════════════════════════════════════════════════


class TestPaymentsGaps:
    def test_handle_successful_payment_flags_suspicious(self, app):
        """أسطر 535/537-539: مبلغ > 3x المتوسط → pending_review + إشعار المشرفين."""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.models.communication import Notification
        from app.services.payments import PaymentGateway, PaymentService

        sid, cid = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        aid, _ = mk_user(app, role="super_admin")
        pid = make_subscription_plan(app, sid, cid)
        sub_id = make_subscription(app, uid, pid, cid)
        make_payment(app, sub_id, amount=10.0, status="approved")  # متوسط المدرسة = 10

        payload = {"metadata": {"subscription_id": str(sub_id)}, "amount": "999999"}

        with app.app_context():
            svc = PaymentService()
            svc._handle_successful_payment(payload, PaymentGateway.CASHU)

            sub = db.session.get(Subscription, sub_id)
            assert sub.status == "pending_review"
            notes = Notification.query.filter_by(user_id=aid, type="payment_review").all()
            assert len(notes) >= 1

    def test_handle_successful_payment_activates_when_normal(self, app):
        """مبلغ طبيعي (لا متوسط سابق → غير مشبوه) → تفعيل مباشر."""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.payments import PaymentGateway, PaymentService

        sid, cid = _setup_class(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        pid = make_subscription_plan(app, sid, cid)
        sub_id = make_subscription(app, uid, pid, cid)

        with app.app_context():
            payload = {"metadata": {"subscription_id": str(sub_id)}, "amount": "100"}
            svc = PaymentService()
            svc._handle_successful_payment(payload, PaymentGateway.CASHU)

            db.session.expire_all()
            sub = db.session.get(Subscription, sub_id)
            assert sub.status == "active"


# ═══════════════════════════════════════════════════════════════════════
# services/school_approvals.py — 51, 99, 106, 146
# ═══════════════════════════════════════════════════════════════════════


class TestSchoolApprovalsGaps:
    def test_approve_missing_link(self, app):
        """سطر 51: رابط دور غير موجود."""
        from app.services.school_approvals import approve_user_role_link

        with app.app_context():
            ok, err = approve_user_role_link(987654321, approver_id=1)
            assert ok is False and "غير موجود" in err

    def test_reject_missing_link(self, app):
        """سطر 99: رفض رابط غير موجود."""
        from app.services.school_approvals import reject_user_role_link

        with app.app_context():
            ok, err = reject_user_role_link(987654321, approver_id=1)
            assert ok is False and "غير موجود" in err

    def test_approve_missing_approver(self, app):
        """سطر 106: رابط صالح بمستخدم منتظر لكن الموافق غير موجود."""
        from app.extensions import db
        from app.models.user import UserRoleLink
        from app.services.school_approvals import approve_user_role_link

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid, approved=False)
        with app.app_context():
            link_id = db.session.scalar(db.select(UserRoleLink.id).where(UserRoleLink.user_id == uid))
            ok, err = approve_user_role_link(link_id, approver_id=987654321)
            assert ok is False
            assert "الموافق غير موجود" in err

    def test_approve_success_by_super_admin(self, app):
        """سطر 106+ (ذرع super_admin): موافقة ناجحة على رابط منتظر."""
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus, UserRoleLink
        from app.services.school_approvals import approve_user_role_link

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid, approved=False)
        aid, _ = mk_user(app, role="super_admin")
        with app.app_context():
            link_id = db.session.scalar(db.select(UserRoleLink.id).where(UserRoleLink.user_id == uid))
            ok, err = approve_user_role_link(link_id, approver_id=aid)
            assert ok is True and err is None
            assert db.session.get(User, uid).approval_status == UserApprovalStatus.approved

    def test_queue_for_school_admin(self, app):
        """سطر 146: مدرسة بمشرفها تُرجع قائمة انتظار (قد تكون فارغة)."""
        from app.services.school_approvals import get_approval_queue_for_user

        sid = make_school(app)
        aid, _ = mk_user(app, role="school_admin", school_id=sid)
        with app.app_context():
            queue = get_approval_queue_for_user(aid)
            assert isinstance(queue, list)

    def test_queue_arms(self, app):
        """أسطر 139/142/146: مستخدم مفقود، super_admin، ومشرف بلا مدرسة."""
        from app.services.school_approvals import get_approval_queue_for_user

        with app.app_context():
            assert get_approval_queue_for_user(987654321) == []  # مستخدم غير موجود
            aid, _ = mk_user(app, role="super_admin")
            assert isinstance(get_approval_queue_for_user(aid), list)  # ذرع super_admin
            admin_no_school, _ = mk_user(app, role="school_admin")  # بلا school_id
            assert get_approval_queue_for_user(admin_no_school) == []  # سطر 146

    def test_queue_for_regular_role_empty(self, app):
        """دور بلا قائمة انتظار → [] فارغة."""
        from app.services.school_approvals import get_approval_queue_for_user

        sid = make_school(app)
        uid, _ = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            assert get_approval_queue_for_user(uid) == []


# ═══════════════════════════════════════════════════════════════════════
# tasks/grading.py — 238-243
# ═══════════════════════════════════════════════════════════════════════


class TestGradingTaskGaps:
    def test_batch_update_grade_item_not_found(self, app, celery_guard):
        """فرع item مفقود/صنف خاطئ → failed."""
        from app.tasks.grading import batch_update_gradebook

        with app.app_context():
            result = batch_update_gradebook(
                _self(), class_id=12345, grade_item_id=67890, entries=[{"student_id": 1, "mark": 90}]
            )
        assert result["status"] == "failed"
        assert "not found" in result["error"]

    def test_batch_update_tx_error(self, app, celery_guard):
        """أسطر 238-240: TxError من tx() → failed مع رسالة."""
        from app.core.db import TxError
        from app.tasks.grading import batch_update_gradebook
        from tests.conftest import make_grade_category, make_grade_item

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            cat_id = make_grade_category(app, cid, "أعمال", 50)
            item_id = make_grade_item(app, cid, cat_id, "واجب", 100)
            with patch("app.core.db.tx", side_effect=TxError("tx boom")):
                result = batch_update_gradebook(
                    _self(), class_id=cid, grade_item_id=item_id, entries=[{"student_id": stu, "mark": 50}]
                )
        assert result["status"] == "failed"
        assert "tx boom" in result["error"]

    def test_batch_update_unexpected_error(self, app, celery_guard):
        """أسطر 241-243: استثناء غير متوقع → failed مع logger.exception."""
        from app.tasks.grading import batch_update_gradebook
        from tests.conftest import make_grade_category, make_grade_item

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            cat_id = make_grade_category(app, cid, "أعمال", 50)
            item_id = make_grade_item(app, cid, cat_id, "واجب", 100)
            with patch("app.core.db.tx", side_effect=RuntimeError("unexpected")):
                result = batch_update_gradebook(
                    _self(), class_id=cid, grade_item_id=item_id, entries=[{"student_id": stu, "mark": 50}]
                )
        assert result["status"] == "failed"
        assert "unexpected" in result["error"]


# ═══════════════════════════════════════════════════════════════════════
# Routes — family 31-32/54-55, schools 29-32, tutoring 52/137-138/341,
# admin 39-42/314/341-342/474, ai 29/77-78, assessment 170-171/510
# ═══════════════════════════════════════════════════════════════════════


class TestFamilyRouteGaps:
    def test_do_link_invalid_code_flashes(self, app):
        """أسطر 31-32: كود ربط غير صالح → flash خطر + إعادة توجيه."""
        client = login_as(app, mk_user(app, role="parent"))
        resp = client.post("/family/link", data={"code": "NOPE1234"}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.location.rstrip("/").endswith("/family")

    def test_do_link_success_flashes(self, app):
        """أسطر 31-32: كود صالح → ربط ناجح + flash نجاح."""
        from app.services.family import generate_link_code

        sid = make_school(app)
        parent = mk_user(app, role="parent")
        stu = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            code, err = generate_link_code(stu[0])
            assert err is None and code

        client = login_as(app, parent)
        resp = client.post("/family/link", data={"code": code}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.location.rstrip("/").endswith("/family")

    def test_generate_code_renders(self, app):
        """الذرع الناجح لتوليد رمز الربط."""
        sid = make_school(app)
        stu = mk_user(app, role="student", school_id=sid)
        resp = login_as(app, stu).get("/family/generate")
        assert resp.status_code == 200

    def test_generate_code_error_redirects_to_dashboard(self, app):
        """أسطر 54-55: فشل التوليد → flash + عودة للوحة التحكم."""
        from app.modules.family import routes as froutes

        sid = make_school(app)
        stu = mk_user(app, role="student", school_id=sid)
        client = login_as(app, stu)
        with patch.object(froutes, "generate_link_code", return_value=(None, "فشل التوليد")):
            resp = client.get("/family/generate", follow_redirects=False)
        assert resp.status_code == 302
        assert "dashboard" in resp.location


class TestSchoolsRouteGaps:
    def test_school_id_or_abort_403_without_school(self, app):
        """أسطر 29-32: مستخدم بلا مدرسة → abort(403) من المساعد."""
        from app.extensions import db
        from app.models.user import User
        from app.modules.schools import routes as sroutes

        uid, _ = mk_user(app, role="school_admin")  # بلا school_id
        with app.app_context():
            with app.test_request_context():
                from flask_login import login_user

                login_user(db.session.get(User, uid))
                with pytest.raises(Forbidden):
                    sroutes._school_id_or_abort()


class TestTutoringRouteGaps:
    def test_profile_without_tutor_profile_404(self, app):
        """سطر 52: مستخدم بلا ملف معلم نشط → abort(404)."""
        sid = make_school(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        resp = app.test_client().get(f"/tutoring/tutors/{tid}")
        assert resp.status_code == 404

    def test_profile_with_active_tutor_renders(self, app):
        """سطر 53: ملف معلم نشط → القالب يُعرض."""
        sid = make_school(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        make_tutor_profile(app, tid)
        resp = app.test_client().get(f"/tutoring/tutors/{tid}")
        assert resp.status_code == 200

    def test_book_non_student_redirects(self, app):
        """أسطر 137-138: غير الطالب يحاول الحجز → تحذير + إعادة توجيه."""
        sid = make_school(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        make_tutor_profile(app, tid)
        client = login_as(app, mk_user(app, role="parent"))
        resp = client.get(f"/tutoring/book/{tid}", follow_redirects=False)
        assert resp.status_code == 302
        assert "/tutoring" in resp.location

    def test_rate_after_24h_window_rejected(self, app):
        """سطر 341: تقييم بعد انقضاء 24 ساعة → flash + إعادة توجيه."""
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        sid = make_school(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        make_tutor_profile(app, tid)
        stu = mk_user(app, role="student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu[0], status="completed")

        with app.app_context():
            sess = db.session.get(TutoringSession, sess_id)
            sess.end_time = datetime.now(UTC) - timedelta(hours=25)
            sess.duration_min = None  # ليُستخدم end_time كما هو
            db.session.commit()

        resp = login_as(app, stu).post(
            f"/tutoring/rate/{sess_id}", data={"rating": 5, "comment": "جيد"}, follow_redirects=False
        )
        assert resp.status_code == 302

    def test_rate_within_24h_renders_form(self, app):
        """الذرع المقابل: ضمن نافذة 24 ساعة → النموذج يُعرض."""
        sid = make_school(app)
        tid, _ = mk_user(app, role="teacher", school_id=sid)
        make_tutor_profile(app, tid)
        stu = mk_user(app, role="student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu[0], status="completed")
        resp = login_as(app, stu).get(f"/tutoring/rate/{sess_id}")
        assert resp.status_code == 200


class TestAdminRouteGaps:
    def test_find_pg_tool_fallback_returns_name(self, app):
        """أسطر 39-42: أداة غير موجودة على النظام → يعيد الاسم كما هو."""
        from app.modules.admin.routes import _find_pg_tool

        assert _find_pg_tool("definitely-not-a-real-tool-xyz") == "definitely-not-a-real-tool-xyz"

    def test_impersonate_super_admin_target_rejected(self, app):
        """سطر 314: super_admin يحاول انتحال super_admin آخر → خطأ + عودة للتفاصيل."""
        a1 = mk_user(app, role="super_admin")
        a2 = mk_user(app, role="super_admin")
        client = login_as(app, a1)
        resp = client.post(f"/admin/users/{a2[0]}/impersonate", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.location.endswith(f"/admin/users/{a2[0]}")

    def test_impersonate_exit_without_session_403(self, app):
        """الذرع 403: خروج من انتحال بلا جلسة نشطة."""
        client = login_as(app, mk_user(app, role="super_admin"))
        resp = client.post("/admin/impersonate/exit", follow_redirects=False)
        assert resp.status_code == 403

    def test_impersonate_exit_error_flashes(self, app):
        """أسطر 341-342: جلسة انتحال نشطة + خطأ من stop_impersonation → flash + عودة."""
        from app.services import impersonation as imod

        sid = make_school(app)
        a1 = mk_user(app, role="super_admin")
        target = mk_user(app, role="student", school_id=sid)
        client = login_as(app, a1)
        assert client.post(f"/admin/users/{target[0]}/impersonate", follow_redirects=False).status_code == 302
        with patch.object(imod, "stop_impersonation", return_value="فشل الإنهاء"):
            resp = client.post("/admin/impersonate/exit", follow_redirects=False)
        assert resp.status_code == 302
        assert "dashboard" in resp.location

    def test_subscription_detail_unknown_status_else_arm(self, app):
        """سطر 474: حالة خارج القوائم المعروفة → فرع else في الخط الزمني.

        القاعدة بعد المايجريشن (كما في CI) تفرض قيد ck_subscription_status يمنع
        إدراج حالات غير معروفة مثل "draft"، لذا نمرّر كائن Subscription غير
        محفوظ مباشرة إلى الدالة (مع تعطيل جلب البيانات فقط) — نفس المنطق،
        بلا تعارض مع قيد القاعدة."""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.models.user import User
        from app.modules.admin import routes as admin_routes
        from flask_login import login_user

        admin_id, _ = mk_user(app, role="super_admin")

        sub = Subscription(user_id=admin_id, plan_id=None, class_id=None, price=Decimal("100"))
        sub.status = "حالة-مجهولة"  # type: ignore[assignment]
        sub.id = 474
        sub.payments = []
        sub.user = MagicMock()
        sub.user.name_ar = "طالب"

        with app.app_context():
            with app.test_request_context():
                login_user(db.session.get(User, admin_id))
                with (
                    patch.object(admin_routes.db, "get_or_404", return_value=sub),
                    patch.object(admin_routes, "render_template", return_value="ok") as rt,
                ):
                    resp = admin_routes.subscription_detail(474)
        assert resp == "ok"
        assert rt.call_args.args[0] == "admin/subscription_detail.html"
        steps = rt.call_args.kwargs["timeline_steps"]
        # الخطوة الأولى (مُرسل) منجزة دائماً، وكل أذرع else غير منجزة وغير نشطة وبلا تاريخ
        assert steps[0]["done"] is True
        for step in steps[1:]:
            assert step["done"] is False
            assert step["active"] is False
            assert step["date"] is None


class TestAiRouteGaps:
    def test_chat_page_renders_sessions_with_meta(self, app):
        """سطر 29: جلسة سابقة بـmeta ورسائل تُعرض في صفحة المحادثة."""
        from app.extensions import db
        from app.models.ai import AiMessage, AiSession

        sid, _ = _setup_class(app)
        uid, email = mk_user(app, role="student", school_id=sid)
        with app.app_context():
            sess = AiSession(user_id=uid, session_type="student_helper", meta={"model": "gpt-4o"})
            db.session.add(sess)
            db.session.flush()
            db.session.add(AiMessage(session_id=sess.id, role="user", content="سؤال"))
            db.session.add(AiMessage(session_id=sess.id, role="assistant", content="جواب"))
            db.session.commit()

        resp = login_as(app, (uid, email)).get("/ai/chat")
        assert resp.status_code == 200
        assert b"gpt-4o" in resp.data

    def test_chat_stream_tx_failure_rolls_back(self, app):
        """أسطر 77-78: فشل tx في finally → rollback ثم remove بلا انهيار."""
        from app.core.db import TxError

        sid, _ = _setup_class(app)
        uid, email = mk_user(app, role="student", school_id=sid)
        client = login_as(app, (uid, email))

        # حصة تينانت سخية (نمط الاختبارات القائمة) + tx يرفع في finally البث فقط
        quota = MagicMock()
        quota.ai_enabled = True
        quota.max_ai_tokens_monthly = 10**9
        with (
            patch("app.services.tenant.get_quota", return_value=quota),
            patch("app.core.db.tx", side_effect=TxError("rollback test")),
        ):
            resp = client.post("/ai/chat/stream", json={"question": "سؤال التدفق"})
        assert resp.status_code == 200
        assert resp.get_data()  # استنزاف كامل يمنع جلسات idle in transaction


class TestAssessmentRouteGaps:
    def test_attempt_start_teacher_redirects(self, app):
        """أسطر 163-165: معلم يبدأ محاولة → تحذير وإعادة توجيه."""
        sid = make_school(app)
        tid, email = mk_user(app, role="teacher", school_id=sid)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj, teacher_id=tid)
        with app.app_context():
            from app.extensions import db
            from app.models.assessment import Quiz

            quiz = Quiz(class_id=cid, title="t", created_by=tid)
            db.session.add(quiz)
            db.session.commit()
            qid = quiz.id

        resp = login_as(app, (tid, email)).get(f"/classes/quizzes/{qid}/attempt", follow_redirects=False)
        assert resp.status_code == 302

    def test_attempt_start_none_defensive_flash(self, app):
        """أسطر 170-171: attempt بلا خطأ → flash خطأ داخلي + إعادة توجيه."""
        from app.modules.assessment import routes as aroutes

        sid, cid = _setup_class(app)
        uid, email = mk_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        with app.app_context():
            from app.extensions import db
            from app.models.assessment import Quiz

            quiz = Quiz(class_id=cid, title="d", created_by=uid)
            db.session.add(quiz)
            db.session.commit()
            qid = quiz.id

        client = login_as(app, (uid, email))
        with patch.object(aroutes, "start_attempt", return_value=(None, None)):
            resp = client.get(f"/classes/quizzes/{qid}/attempt", follow_redirects=False)
        assert resp.status_code == 302

    def test_quiz_stats_no_data_redirects(self, app):
        """سطر 510: stats فارغة → flash info + عودة لنتائج الاختبار."""
        from app.modules.assessment import routes as aroutes

        sid = make_school(app)
        tid, email = mk_user(app, role="teacher", school_id=sid)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj, teacher_id=tid)
        with app.app_context():
            from app.extensions import db
            from app.models.assessment import Quiz

            quiz = Quiz(class_id=cid, title="empty", created_by=tid)
            db.session.add(quiz)
            db.session.commit()
            qid = quiz.id

        client = login_as(app, (tid, email))
        with patch.object(aroutes, "get_quiz_stats", return_value=None):
            resp = client.get(f"/classes/quiz/{qid}/stats", follow_redirects=False)
        assert resp.status_code == 302
        assert "results" in resp.location
