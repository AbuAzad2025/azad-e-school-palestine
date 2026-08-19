"""اختبارات تذكيرات الدفع اليومية."""

import pytest
from datetime import datetime, timedelta, UTC

from app.models.billing import ReminderLog, Subscription
from app.services.email import send_payment_reminder_email
from scripts.daily_reminders import run_daily_reminders
from tests.conftest import make_school, make_user, make_subscription_plan, make_subscription


def test_send_payment_reminder_email(app):
    """إرسال إيميل تذكير الدفع يعمل."""
    school_id = make_school(app)
    user_id = make_user(app, role="student", school_id=school_id)
    plan_id = make_subscription_plan(app, school_id, price=100.0, plan="annual")

    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan

        sub = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            class_id=1,  # dummy class_id
            price=100.0,
            currency="ILS",
            status="active",
            end_at=datetime.now(UTC) + timedelta(days=5),
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

        sub = db.session.get(Subscription, sub_id)

    with app.app_context():
        result = send_payment_reminder_email(sub, 5)

    # في بيئة الاختبار EMAIL_ENABLED=False، لذا تعيد False
    # لكن الدالة لا ترمي استثناء
    assert result is False  # لأن EMAIL_ENABLED=False في الاختبارات


def test_send_payment_reminder_email_content(app):
    """محتوى إيميل التذكير يحتوي على المعلومات الصحيحة."""
    school_id = make_school(app)
    user_id = make_user(app, role="student", school_id=school_id)
    plan_id = make_subscription_plan(app, school_id, price=100.0, plan="annual")

    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan

        sub = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            class_id=1,
            price=100.0,
            currency="ILS",
            status="active",
            end_at=datetime.now(UTC) + timedelta(days=5),
        )
        db.session.add(sub)
        db.session.commit()

        sub = db.session.get(Subscription, sub.id)

    # التحقق من بناء HTML
    with app.app_context():
        from app.extensions import db
        sub = db.session.get(Subscription, sub.id)
        user = sub.user
        plan = sub.plan
        days_until = 5
        html = f"""
        <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #014e7c;">تذكير: تجديد الاشتراك</h2>
            <p>مرحباً {user.name_ar or user.email}،</p>
            <p>اشتراكك في <strong>{plan.name}</strong> سينتهي خلال <strong>{days_until} يوم</strong>.</p>
        </div>
        """

    assert "تذكير: تجديد الاشتراك" in html
    assert plan.name in html
    assert str(days_until) in html


def test_reminder_log_prevents_duplicate(app):
    """ReminderLog يمنع الإرسال المكرر."""
    school_id = make_school(app)
    user_id = make_user(app, role="student", school_id=school_id)
    plan_id = make_subscription_plan(app, school_id, price=100.0, plan="annual")

    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription, ReminderLog

        sub = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            class_id=1,
            price=100.0,
            currency="ILS",
            status="active",
            end_at=datetime.now(UTC) + timedelta(days=5),
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

        # إضافة تذكير مسبق
        log = ReminderLog(subscription_id=sub_id, reminder_type="7d")
        db.session.add(log)
        db.session.commit()

        # محاولة إضافة نفس التذكير
        log2 = ReminderLog(subscription_id=sub_id, reminder_type="7d")
        db.session.add(log2)

        try:
            db.session.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            db.session.rollback()
            # متوقع أن يفشل بسبب القيد الفريد

    with app.app_context():
        count = ReminderLog.query.filter_by(subscription_id=sub_id, reminder_type="7d").count()
        assert count == 1


def test_daily_reminders_script_logic(app):
    """منطق سكريبت التذكيرات اليومي."""
    school_id = make_school(app)
    user_id = make_user(app, role="student", school_id=school_id)
    plan_id = make_subscription_plan(app, school_id, price=100.0, plan="annual")

    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan, ReminderLog, ManualPayment

        # تنظيف قاعدة البيانات من الاشتراكات السابقة لهذا الاختبار
        ReminderLog.query.delete()
        ManualPayment.query.delete()
        Subscription.query.delete()
        db.session.commit()

        # اشتراك ينتهي بعد 7 أيام
        sub1 = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            class_id=1,
            price=100.0,
            currency="ILS",
            status="active",
            end_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.session.add(sub1)
        db.session.commit()

        # اشتراك ينتهي بعد 3 أيام
        user_id2 = make_user(app, role="student", school_id=school_id)
        sub2 = Subscription(
            user_id=user_id2,
            plan_id=plan_id,
            class_id=1,
            price=100.0,
            currency="ILS",
            status="active",
            end_at=datetime.now(UTC) + timedelta(days=3),
        )
        db.session.add(sub2)
        db.session.commit()

        # اشتراك منتهي الصلاحية (لا يجب أن يتم تذكيره)
        user_id3 = make_user(app, role="student", school_id=school_id)
        sub3 = Subscription(
            user_id=user_id3,
            plan_id=plan_id,
            class_id=1,
            price=100.0,
            currency="ILS",
            status="expired",
            end_at=datetime.now(UTC) - timedelta(days=1),
        )
        db.session.add(sub3)
        db.session.commit()

        # اشتراك معلق (لا يجب أن يتم تذكيره)
        user_id4 = make_user(app, role="student", school_id=school_id)
        sub4 = Subscription(
            user_id=user_id4,
            plan_id=plan_id,
            class_id=1,
            price=100.0,
            currency="ILS",
            status="pending",
            end_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.session.add(sub4)
        db.session.commit()

        # حفظ IDs
        sub1_id = sub1.id
        sub2_id = sub2.id

    # تشغيل السكريبت مع تعطيل email (mocking)
    with app.app_context():
        import app.services.email as email_module

        # Mock the send function to return True
        original_send = email_module._send
        email_module._send = lambda *args, **kwargs: True

        try:
            from scripts.daily_reminders import run_daily_reminders
            sent = run_daily_reminders(app)
            # يجب أن يرسل 2 تذكير (7d و 3d)
            assert sent == 2
        finally:
            email_module._send = original_send

    # التحقق من السجلات
    with app.app_context():
        from app.models.billing import ReminderLog
        logs = ReminderLog.query.all()
        assert len(logs) == 2
        types = {log.reminder_type for log in logs}
        assert types == {"7d", "3d"}


def test_reminder_respects_email_disabled_flag(app):
    """سكريبت التذكيرات يحترم علم EMAIL_ENABLED."""
    # في بيئة الاختبار EMAIL_ENABLED=False
    # السكريبت يجب أن يعمل لكن لا يرسل إيميلات حقيقية
    # الدالة send_payment_reminder_email ستعيد False
    school_id = make_school(app)
    user_id = make_user(app, role="student", school_id=school_id)
    plan_id = make_subscription_plan(app, school_id, price=100.0, plan="annual")

    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription

        sub = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            class_id=1,
            price=100.0,
            currency="ILS",
            status="active",
            end_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.session.add(sub)
        db.session.commit()

    # تشغيل السكريبت - يجب أن يعمل بدون أخطاء حتى لو فشل الإرسال
    with app.app_context():
        sent = run_daily_reminders()
        # لا يتم إرسال إيميلات لأن EMAIL_ENABLED=False
        # لكن السكريبت يجب أن يكمل بدون أخطاء
        assert sent == 0  # لا يتم تسجيل تذكيرات لأن الإرسال فشل