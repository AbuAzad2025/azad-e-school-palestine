"""Round L — branch closure: service-layer partial branches.

Targets the branch arcs still reported missing by CI (run 43296221930):

- app/services/ai.py: cached client short-circuit, usage recording with no
  rate limiter / budget tracker, a real stream with no content and no usage,
  and ``ask_question`` over a stream that ends without a ``data:`` frame.
- app/services/base.py: ``list`` filters with ``None``/unknown columns and
  ``update`` with unknown attributes.
- app/services/export.py: repeated student rows and entries without a mark.
- app/services/grade_calc.py: items with no max mark.
- app/services/offline.py: download ids that no longer exist.
- app/services/payments.py: gateway loading without config, school derivation
  without a class row, review flagging without a school, and ledger entries for
  subscriptions without an owner.
- app/services/quiz_stats.py: a quiz with no attempts.
- app/services/gamification.py: early-bird events without a deadline and badge
  loops where nothing is awarded.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from tests.conftest import (
    _db,
    _uid,
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_school,
    make_subject,
    make_user,
)

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk_user(app, role: str = "student", school_id=None):
    email = f"rnd-l-{_uid()}@test.com"
    return make_user(app, role=role, school_id=school_id, email=email), email


def _setup_class(app, teacher_id=None):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    cid = make_class(app, sid, gid, make_subject(app), teacher_id=teacher_id)
    return sid, cid


async def _collect(gen):
    return [chunk async for chunk in gen]


# ═════════════════════════════ ai ═════════════════════════════


class TestAiBranchClosure:
    def test_get_client_returns_cached_client(self, app):
        """عميل مُخزَّن سابقاً يُعاد بلا إنشاء جديد."""
        from app.services import ai as ai_mod
        from app.services.ai import AiService

        sentinel = object()
        original = AiService._client
        try:
            AiService._client = sentinel
            with app.app_context(), patch.object(ai_mod, "OPENAI_AVAILABLE", True):
                assert AiService()._get_client() is sentinel
        finally:
            AiService._client = original

    def test_record_usage_without_limiter_or_tracker(self, app):
        """غياب محدّد المعدل ومتتبّع الميزانية لا يمنع تسجيل الاستخدام."""
        from app.services.ai import AiService

        uid, _ = mk_user(app)
        original = (AiService._rate_limiter, AiService._budget_tracker)
        try:
            with app.app_context():
                svc = AiService()
                # البانية تُنشئ المحدّدات عند غيابها، فالتبديل بعدها لا قبلها.
                AiService._rate_limiter = None
                AiService._budget_tracker = None
                svc._record_usage(100, 20, uid, "chat")
                from app.models.ai import AiUsageLog

                assert AiUsageLog.query.filter_by(user_id=uid).count() == 1
        finally:
            AiService._rate_limiter, AiService._budget_tracker = original

    def test_real_stream_without_content_or_usage(self, app):
        """بثّ بلا نصّ وبلا usage: لا تُحفظ رسالة ولا يُسجَّل استخدام."""
        from app.services.ai import AiService

        uid, _ = mk_user(app)
        empty_chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))], usage=None)

        class _FakeStream:
            def __aiter__(self):
                return self

            def __init__(self):
                self._chunks = [empty_chunk, empty_chunk]
                self._i = 0

            async def __anext__(self):
                if self._i >= len(self._chunks):
                    raise StopAsyncIteration
                self._i += 1
                return self._chunks[self._i - 1]

        class _FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    async def create(**_kwargs):
                        return _FakeStream()

        with app.app_context():
            svc = AiService()
            svc._record_usage = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no usage expected"))
            with (
                patch.object(svc, "_check_limits", return_value=(True, "")),
                patch.object(svc, "_get_client", return_value=_FakeClient()),
            ):
                chunks = asyncio.run(_collect(svc._real_stream([], 1)))
            from app.models.ai import AiMessage

            assert chunks[-1] == "data: [DONE]\n\n"
            assert AiMessage.query.filter_by(session_id=1, role="assistant").count() == 0

    def test_ask_question_ignores_non_sse_chunk_and_missing_session(self, app):
        """إطار غير SSE يُتجاهل، وانتهاء البثّ يجلب الجلسة (أو None)."""
        from app.services.ai import AiService

        uid, _ = mk_user(app)

        async def _synthetic(*_a, **_k):
            yield "heartbeat\n\n"
            yield 'data: {"delta": "أ"}\n\n'

        with app.app_context():
            svc = AiService()
            with patch.object(svc, "ask_question_stream", _synthetic):
                result = asyncio.run(svc.ask_question(uid, "سؤال"))
        assert result["answer"] == "أ"
        assert result["session_id"] is None


# ═════════════════════════════ base service ═════════════════════════════


class TestBaseServiceBranchClosure:
    def test_list_skips_none_and_unknown_filters(self, app):
        """مرشّح بقيمة None أو عمود غير موجود لا يُبنى له شرط."""
        from app.models.user import User
        from app.services.base import BaseService

        class _UserService(BaseService[User]):
            model = User

        uid, _ = mk_user(app)
        with app.app_context():
            result = _UserService.list(filters={"email": None, "not_a_column": 1})
            assert result.meta.total >= 1
            narrowed = _UserService.list(filters={"id": uid})
            assert [u.id for u in narrowed.items] == [uid]

    def test_update_ignores_unknown_attributes(self, app):
        """مفتاح لا يوجد كسِمة على الكيان يُتجاهل بدل أن يرفع خطأ."""
        from app.models.user import User
        from app.services.base import BaseService

        class _UserService(BaseService[User]):
            model = User

        uid, _ = mk_user(app)
        with app.app_context():
            updated = _UserService.update(uid, name_ar="اسم محدَّث", not_a_column="x")
            assert updated is not None
            assert updated.name_ar == "اسم محدَّث"


# ═════════════════════════════ export ═════════════════════════════


class TestExportBranchClosure:
    def test_moe_export_handles_repeated_students_and_missing_marks(self, app):
        """طالب له درجتان (إحداهما بلا علامة) يُحسب مرة واحدة بمعدّله."""
        from app.services.export import export_moe_format

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, school_id=sid)
        make_class_member(app, cid, stu)
        cat = make_grade_category(app, cid, "الفصل", 100)
        item_a = make_grade_item(app, cid, cat, "أ", 20)
        item_b = make_grade_item(app, cid, cat, "ب", 20)
        make_grade_entry(app, stu, item_a, 10)
        make_grade_entry(app, stu, item_b, None)

        with app.app_context():
            data = export_moe_format(school_id=sid)
        assert isinstance(data, bytes)
        assert len(data) > 0


# ═════════════════════════════ grade calc ═════════════════════════════


class TestGradeCalcBranchClosure:
    def test_item_without_max_mark_is_excluded_from_totals(self, app):
        """بند بلا درجة قصوى لا يزيد مقام القسم ولا مقسومه في ملخّص الصفّ."""
        from app.services.grade_calc import class_grades_summary

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, school_id=sid)
        make_class_member(app, cid, stu)
        cat = make_grade_category(app, cid, "الفصل", 100)
        scored = make_grade_item(app, cid, cat, "مُقيَّم", 20)
        unscored = make_grade_item(app, cid, cat, "بلا قصوى", None)
        make_grade_entry(app, stu, scored, 15)
        make_grade_entry(app, stu, unscored, 5)

        with app.app_context():
            rows = class_grades_summary(cid)
        row = next(r for r in rows if r["student_id"] == stu)
        assert row["categories"][0]["category_pct"] == 75.0
        assert row["final_grade"] == 75.0


# ═════════════════════════════ offline ═════════════════════════════


class TestOfflineBranchClosure:
    def test_mark_downloaded_and_remove_ignore_missing_rows(self, app):
        """معرّف تنزيل غير موجود لا يفعل شيئاً ولا يرفع خطأ."""
        from app.services.offline import mark_downloaded, remove_offline

        with app.app_context():
            mark_downloaded(987_654_321)
            remove_offline(987_654_321)


# ═════════════════════════════ payments ═════════════════════════════


class TestPaymentsBranchClosure:
    def test_gateways_without_configuration_are_skipped(self, app):
        """بوابة بلا إعداد لا تُنشأ."""
        from app.services.payments import PaymentService

        with patch.object(PaymentService, "_get_gateway_config", return_value=None):
            service = PaymentService()
        assert service.gateways == {}

    def test_school_derivation_without_class_row(self, app):
        """اشتراك يشير إلى صفّ غير موجود ينتقل إلى اشتقاق الخطة."""
        from app.services.payments import PaymentService

        with app.app_context():
            assert (
                PaymentService._resolve_subscription_school(SimpleNamespace(class_id=987_654_321, plan_id=None)) is None
            )

    def test_flag_for_review_without_school_notifies_all_admins(self, app):
        """غياب المدرسة يعني إشعار المشرفين بلا تقييد — والحالة تصبح pending_review."""
        from app.models.billing import Subscription
        from app.services.payments import PaymentService

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, school_id=sid)
        mk_user(app, "super_admin")
        plan_id = make_subscription_plan_for(app, sid, cid)
        with app.app_context():
            sub = Subscription(user_id=stu, plan_id=plan_id, class_id=cid, price=Decimal("10.00"), status="pending")
            _db.session.add(sub)
            _db.session.commit()
            sub_id = sub.id
            with patch("app.services.communication.notify") as notified:
                PaymentService()._flag_for_review(sub, "مراجعة", "تفاصيل")
            _db.session.expire_all()
            assert _db.session.get(Subscription, sub_id).status == "pending_review"
            assert notified.called

    def test_ledger_entry_for_ownerless_subscription_has_no_wallet(self, app):
        """اشتراك بلا مالك لا يفتح محفظة، والقيد يُكتب بالمصدر الخارجي فقط."""
        from app.models.billing import Subscription
        from app.models.wallet import WalletTransaction
        from app.services.payments import PaymentGateway, PaymentService

        sid, cid = _setup_class(app)
        plan_id = make_subscription_plan_for(app, sid, cid)
        with app.app_context():
            sub = Subscription(user_id=None, plan_id=plan_id, class_id=cid, price=Decimal("10.00"), currency="ILS")
            PaymentService()._create_ledger_entry(sub, Decimal("10.00"), PaymentGateway.CASHU)
            row = WalletTransaction.query.filter_by(school_id=sid).order_by(WalletTransaction.id.desc()).first()
            assert row is not None
            assert row.destination_wallet_id is None


# ═════════════════════════════ quiz stats ═════════════════════════════


class TestQuizStatsBranchClosure:
    def test_quiz_without_attempts_reports_zeroed_stats(self, app):
        """اختبار بلا محاولات يعود مبكراً بإحصاءات صفرية بلا تحليل أسئلة."""
        from app.models.assessment import Question, Quiz
        from app.services.quiz_stats import get_quiz_stats

        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        with app.app_context():
            quiz = Quiz(class_id=cid, title="اختبار", duration_min=10, created_by=tid, status="published")
            _db.session.add(quiz)
            _db.session.flush()
            _db.session.add(
                Question(quiz_id=quiz.id, type="true_false", prompt="س", correct_answer={"value": True}, mark=5.0)
            )
            _db.session.commit()
            stats = get_quiz_stats(quiz.id)
        assert stats is not None
        assert stats.total_attempts == 0
        assert stats.question_stats == []
        assert stats.score_distribution == {}


# ═════════════════════════════ gamification ═════════════════════════════


class TestGamificationBranchClosure:
    def test_early_bird_event_without_deadline_is_not_awarded(self, app):
        """حدث تسليم بلا موعد نهائي لا يمنح شارة «المبكر»."""
        from app.models.gamification import Badge, BadgeCriteriaType
        from app.services.gamification import check_and_award_badges

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, school_id=sid)
        with app.app_context():
            badge = Badge(
                name="مبكر",
                icon_name="clock",
                criteria_type=BadgeCriteriaType.early_bird,
                is_active=True,
            )
            _db.session.add(badge)
            _db.session.commit()
            awarded = check_and_award_badges(stu, "assignment_submitted", {"submitted_at": "2026-01-01T00:00:00Z"})
        assert awarded == []

    def test_badge_failing_award_write_is_not_returned(self, app):
        """فشل كتابة منح الشارة لا يُضاف إلى القائمة المُعادة."""
        from app.models.gamification import Badge, BadgeCriteriaType
        from app.services import gamification as gam_mod
        from app.services.gamification import check_and_award_badges

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, school_id=sid)
        with app.app_context():
            badge = Badge(
                name="أول اختبار",
                icon_name="star",
                criteria_type=BadgeCriteriaType.first_quiz,
                is_active=True,
            )
            _db.session.add(badge)
            _db.session.commit()
            with patch.object(gam_mod, "award_badge", return_value=None):
                awarded = check_and_award_badges(stu, "quiz_submitted", {})
        assert awarded == []


def make_subscription_plan_for(app, school_id: int, class_id: int) -> int:
    from tests.conftest import make_subscription_plan

    return make_subscription_plan(app, school_id, class_id=class_id, price=10.0)
