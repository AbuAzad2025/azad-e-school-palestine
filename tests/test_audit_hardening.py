"""اختبارات انحدار لإصلاحات التدقيق الأمني (P0/P1/P2).

تغطي: ذرّية الدفع اليدوي، Decimal المالي، القيد الذرّي للخصم، حماية الاعتماد المكرر،
رموز التفعيل/الإعادة أحادية الاستخدام، قفل تسليم الاختبارات، المؤقت الخادمي، تحقق المدخلات.
"""

import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from app.core.db import TxError
from app.core.tokens import make_activation_token, make_reset_token, read_reset_token
from app.extensions import db as _db
from app.models.assessment import Answer, Question, Quiz, QuizAttempt
from app.models.billing import DiscountCode, ManualPayment, Subscription, SubscriptionPlan
from app.models.class_room import ClassRoom
from app.models.school import Grade, School, Subject
from app.services.assessment import (
    deadline_exceeded,
    save_answer,
    start_attempt,
    submit_attempt,
)
from app.services.auth import confirm_email, reset_password
from app.services.billing import (
    apply_discount_code,
    approve_payment,
    create_discount_code,
    money,
    record_manual_payment,
    subscription_payment_summary,
)
from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ═══════════════════ P1-08: Decimal المالي ═══════════════════


def test_money_quantizes_half_up():
    assert money("10.005") == money(10.01)  # ROUND_HALF_UP وليس bankers
    assert str(money(19.999)) == "20.00"
    assert str(money(100)) == "100.00"


def test_create_plan_stores_decimal(app):
    with app.app_context():
        school_id = make_school(app)
        from app.services.billing import create_plan

        plan, error = create_plan(school_id=school_id, name="خطة", plan="annual", price=99.987)
        assert error is None
        assert plan.price == money("99.99")
        from decimal import Decimal

        assert isinstance(plan.price, Decimal)


# ═══════════════════ P0-04: ذرّية الدفع اليدوي + الإيصال ═══════════════════


def _png_file() -> FileStorage:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    return FileStorage(stream=BytesIO(png), filename=f"r{_uid()}.png", content_type="image/png")


def test_record_manual_payment_with_receipt_saves_both(app):
    """P0-04: الإيصال يُحفظ بنفس المعاملة — payment.id محسوم قبل الربط."""
    with app.app_context():
        school_id = make_school(app)
        user_id = make_user(app, role="student")
        plan_id = make_subscription_plan(app, school_id)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        sub_id = make_subscription(app, user_id, plan_id, class_id)
        sub = _db.session.get(Subscription, sub_id)

        payment, error = record_manual_payment(sub, f"ref-{_uid()}", 50.5, receipt_file=_png_file())
        assert error is None
        assert payment is not None
        fresh = ManualPayment.query.get(payment.id)
        assert len(fresh.receipts) == 1
        assert fresh.amount == money("50.50")


# ═══════════════════ P1-09: الخصم الذرّي ═══════════════════


def _discount_code(app, school_id, max_uses=1):
    code, error = create_discount_code(
        school_id=school_id,
        code=f"D-{_uid()}",
        name="خصم",
        type_="fixed",
        value=30,
        max_uses=max_uses,
    )
    assert error is None
    return code


def test_discount_atomic_guard_exhausts_after_max(app):
    with app.app_context():
        school_id = make_school(app)
        user_id = make_user(app, role="student")
        plan_id = make_subscription_plan(app, school_id, price=100)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        sub_id = make_subscription(app, user_id, plan_id, class_id)
        code = _discount_code(app, school_id, max_uses=1)

        first = apply_discount_code(sub_id, code.code)
        assert first[0] is not None and first[1] is None

        # الاستخدام الثاني يجب أن يُرفض (لا تجاوز max_uses)
        second = apply_discount_code(sub_id, code.code)
        assert second[0] is None
        assert "استنفاد" in second[1]

        dc = DiscountCode.query.filter_by(code=code.code).first()
        assert dc.used_count == 1
        sub = _db.session.get(Subscription, sub_id)
        assert sub.price == money("70.00")  # 100 - 30 بلا كسور عائمة


# ═══════════════════ P2-10: حماية الاعتماد المكرر ═══════════════════


def test_approve_payment_rejects_double_approval(app):
    with app.app_context():
        school_id = make_school(app)
        user_id = make_user(app, role="student")
        plan_id = make_subscription_plan(app, school_id)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        sub_id = make_subscription(app, user_id, plan_id, class_id)
        sub = _db.session.get(Subscription, sub_id)
        payment, _ = record_manual_payment(sub, f"ref-{_uid()}", 100)

        approve_payment(payment, reviewer_id=user_id)
        with pytest.raises(TxError):
            approve_payment(payment, reviewer_id=user_id)


def test_payment_summary_decimal(app):
    with app.app_context():
        school_id = make_school(app)
        user_id = make_user(app, role="student")
        plan_id = make_subscription_plan(app, school_id, price=200)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        sub_id = make_subscription(app, user_id, plan_id, class_id, price=200)
        summary = subscription_payment_summary(sub_id)
        assert summary["total_price"] == money("200.00")
        assert summary["balance"] == money("200.00")


# ═══════════════════ P1-01 / P1-02: الرموز ═══════════════════


def test_confirm_email_requires_valid_token(app):
    with app.app_context():
        user_id = make_user(app, approved=True)
        from app.models.user import User

        user = _db.session.get(User, user_id)

        token = make_activation_token(user.id, user.email)
        assert confirm_email(user.id, token) is True
        assert user.is_verified is True

        # رمز فاسد أو uid مختلف → رفض (لا تفعيل بمعرفة البريد فقط)
        assert confirm_email(user.id, "garbage-token") is False


def test_reset_token_single_use_and_session_invalidation(app):
    with app.app_context():
        user_id = make_user(app, approved=True)
        from app.models.user import User

        user = _db.session.get(User, user_id)
        old_get_id = user.get_id()

        token = make_reset_token(user.id, user.email, user.password_changed_at)
        uid, email, pc = read_reset_token(token)
        assert uid == user.id and pc is None

        err = reset_password(token, "NewStrong!Pass9")
        assert err is None
        stamp1 = user.password_changed_at
        assert stamp1 is not None
        # الجلسات القديمة تُبطل عبر get_id
        assert user.get_id() != old_get_id

        # إعادة استخدام نفس الرمز → مرفوض فوراً
        err2 = reset_password(token, "Another!Pass99")
        assert err2 is not None
        assert user.password_changed_at == stamp1


# ═══════════════════ أدوات مساعدة للاختبارات ═══════════════════


def _make_quiz_with_question(app, teacher_id=None, duration_min=None):
    school_id = make_school(app)
    student_id = make_user(app, role="student")
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)
    quiz = Quiz(class_id=class_id, title=f"اختبار {_uid()}", duration_min=duration_min, attempts_allowed=2)
    _db.session.add(quiz)
    _db.session.flush()
    q = Question(quiz_id=quiz.id, type="mcq", prompt="سؤال؟", mark=5, correct_answer={"index": 1})
    _db.session.add(q)
    _db.session.commit()
    return quiz.id, student_id, class_id


# ═══════════════════ P1-06: قفل التسليم المزدوج ═══════════════════


def test_submit_attempt_locks_against_double_submit(app):
    with app.app_context():
        quiz_id, student_id, _ = _make_quiz_with_question(app)
        attempt, error = start_attempt(_db.session.get(Quiz, quiz_id), student_id)
        assert error is None
        answer = Answer(attempt_id=attempt.id, question_id=_db.session.get(Quiz, quiz_id).questions[0].id,
                        answer={"index": 1})
        _db.session.add(answer)
        _db.session.commit()

        score1 = submit_attempt(attempt)
        assert score1 == 5.0

        # تسليم ثانٍ (سباق أو تلاعب) → TxError وليس درجة/بريد مكرر
        with pytest.raises(TxError):
            submit_attempt(attempt)


# ═══════════════════ P1-11: المؤقت الخادمي ═══════════════════


def test_deadline_enforced_server_side(app):
    with app.app_context():
        quiz_id, student_id, _ = _make_quiz_with_question(app, duration_min=10)
        quiz = _db.session.get(Quiz, quiz_id)
        attempt, _ = start_attempt(quiz, student_id)

        # داخل الوقت: الحفظ مقبول والمؤقت غير متجاوز
        assert deadline_exceeded(attempt) is False
        save_answer(attempt, quiz.questions[0].id, {"index": 1})

        # محاكاة مرور الوقت: started_at منذ 20 دقيقة في اختبار مدته 10 دقائق
        attempt.started_at = datetime.now(UTC) - timedelta(minutes=20)
        _db.session.commit()
        assert deadline_exceeded(attempt) is True

        # الحفظ بعد انتهاء الوقت → مرفوض برسالة واضحة
        with pytest.raises(TxError) as exc:
            save_answer(attempt, quiz.questions[0].id, {"index": 0})
        assert "انتهى وقت" in str(exc.value)

        # التصحيح التلقائي بعد المهلة يعتمد المحفوظ فقط
        score = submit_attempt(attempt, allow_after_deadline=True)
        assert score == 5.0  # الإجابة الأولى (الصحيحة) هي التي اعتُمدت


def test_start_attempt_sets_started_at(app):
    with app.app_context():
        quiz_id, student_id, _ = _make_quiz_with_question(app, duration_min=15)
        attempt, _ = start_attempt(_db.session.get(Quiz, quiz_id), student_id)
        assert attempt.started_at is not None


# ═══════════════════ P2-12: تحقق المدخلات ═══════════════════


def test_parse_answer_bad_mcq_index_aborts_400(app):
    from werkzeug.exceptions import BadRequest

    from app.modules.assessment.routes import _parse_answer

    q = Question(type="mcq", prompt="x")
    with pytest.raises(BadRequest):
        _parse_answer(q, "not-an-int")


# ═══════════════════ P2-07/P1-05: القيود الجزئية ═══════════════════


def test_partial_indexes_exist(app):
    with app.app_context():
        rows = _db.session.execute(
            _db.text(
                "SELECT indexname FROM pg_indexes WHERE indexname IN "
                "('uq_subscription_active', 'uq_attempt_open_per_quiz_student')"
            )
        ).fetchall()
        names = {r[0] for r in rows}
        assert "uq_subscription_active" in names
        assert "uq_attempt_open_per_quiz_student" in names


def test_resubscribe_allowed_after_expiry_same_plan(app):
    """P2-07: بعد انتهاء اشتراك يمكن إنشاء اشتراك جديد لنفس الخطة."""
    with app.app_context():
        school_id = make_school(app)
        user_id = make_user(app, role="student")
        plan_id = make_subscription_plan(app, school_id)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))

        expired = Subscription(
            user_id=user_id, plan_id=plan_id, class_id=class_id, price=100, status="expired"
        )
        _db.session.add(expired)
        _db.session.commit()

        active = Subscription(user_id=user_id, plan_id=plan_id, class_id=class_id, price=100, status="active")
        _db.session.add(active)
        _db.session.commit()  # يجب أن ينجح — الفهرس الجزئي على active فقط
        assert active.id is not None
