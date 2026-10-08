"""سيناريوهات E2E تشغيلية — دورات حياة كاملة (docs/E2E_SCENARIOS.md).

كل سيناريو يُغلق دورة حياة حقيقية: تهيئة ← تشغيل ← تغيير حالة ← تحقق مالي/أكاديمي.
البيانات واقعية (أسماء عربية، مبالغ ILS، مراجع إيصالات)، والتشغيل عبر الواجهات
الحقيقية (test client + طبقة الخدمات الرسمية) لا كتابة قاعدة مباشرة.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from tests.conftest import (
    make_class,
    make_class_member,
    make_family_link,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_individual_user,
    make_lesson,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tenant_quota,
    make_tutor_profile,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    """مستوى صفّ فريد لكل مدرسة (قيد التفرد في المخطط)."""
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def _mk_user(app, role: str, school_id=None):
    email = f"e2e-{role}-{make_school.__module__ and ''}{_next_level(0)}-{id(app) & 0xFFFF}@test.com"
    uid = make_user(app, role=role, school_id=school_id, approved=True, email=email)
    return uid, email


def _login(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _school_bundle(app, name_ar: str):
    """مدرسة كاملة: مدير + معلّم + طالبان + ولي أمر + صف نشط بأعضائه."""
    sid = make_school(app, name_ar=name_ar)
    admin_uid, admin_email = _mk_user(app, "school_admin", sid)
    teacher_uid, teacher_email = _mk_user(app, "teacher", sid)
    s1_uid, s1_email = _mk_user(app, "student", sid)
    s2_uid, s2_email = _mk_user(app, "student", sid)
    parent_uid, _parent_email = _mk_user(app, "parent", sid)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subject_id = make_subject(app)
    cid = make_class(app, sid, gid, subject_id, teacher_id=teacher_uid)
    make_class_member(app, cid, s1_uid)
    make_class_member(app, cid, s2_uid)
    make_family_link(app, parent_uid, s1_uid)
    return {
        "sid": sid,
        "cid": cid,
        "gid": gid,
        "subject_id": subject_id,
        "admin": (admin_uid, admin_email),
        "teacher": (teacher_uid, teacher_email),
        "students": [(s1_uid, s1_email), (s2_uid, s2_email)],
        "parent": parent_uid,
    }


# ═══════════════════════════════════════════════════════════════════════════
# S1 — تأسيس مدينتين مدرسيتين مستقلتين بكل الأدوار
# ═══════════════════════════════════════════════════════════════════════════


class TestS1OnboardingLifecycle:
    def test_two_schools_full_roles_onboard_and_login(self, app):

        a = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        b = _school_bundle(app, "مدرسة النور الأساسية – نابلس")
        assert a["sid"] != b["sid"]

        # كل دور يدخل فعلياً: الجلسة تعمل، والصفحة الرئيسية تُصيَّر أو توجّه للوحة الدور
        for bundle in (a, b):
            for _uid, email in (bundle["admin"], bundle["teacher"], *bundle["students"]):
                client = _login(app, email)
                resp = client.get("/")
                assert resp.status_code in (200, 302), email
                location = resp.headers.get("Location") or ""
                assert "/auth/login" not in location, f"{email} لم تُنشأ جلسته"
            # ولي الأمر يدخل ويطالع إشعاراته (صفحة عامة لكل الأدوار المسجلة)
            with app.app_context():
                from app.models.user import User

                parent_email = app.extensions["sqlalchemy"].session.get(User, bundle["parent"]).email
            client = _login(app, parent_email)
            assert client.get("/notifications", follow_redirects=True).status_code == 200

        # تسجيل خروج فعلي يُنهي الجلسة: الصفحة المحمية توجّه لصفحة الدخول
        client = _login(app, a["students"][0][1])
        client.post("/auth/logout")
        resp = client.get("/notifications", follow_redirects=True)
        assert resp.status_code == 200
        assert "/auth/login" in resp.request.path or "login" in resp.get_data(as_text=True)[:2000].lower()


# ═══════════════════════════════════════════════════════════════════════════
# S2 — عزل التينانتس التشغيلي: طالب مدرسة A أمام مسارات مدرسة B
# ═══════════════════════════════════════════════════════════════════════════


class TestS2TenantIsolationProbes:
    def test_cross_tenant_probes_never_leak_content(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.class_room import ClassRoom

        a = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        b = _school_bundle(app, "مدرسة النور الأساسية – نابلس")

        with app.app_context():

            def _mark():
                row = db.session.get(ClassRoom, b["cid"])
                row.name = "صف الفيزياء السري – مدرسة النور"

            tx(_mark)

        secret = "صف الفيزياء السري – مدرسة النور"
        student_a_client = _login(app, a["students"][0][1])
        teacher_a_client = _login(app, a["teacher"][1])

        # طالب A: عرض صفّ B، تقدّمه فيه، وحضوره — رفض صريح بلا أي تسريب محتوى
        for resp in (
            student_a_client.get(f"/classes/{b['cid']}/lessons"),
            student_a_client.get(f"/progress/class/{b['cid']}"),
        ):
            assert resp.status_code in (403, 404)
            assert secret not in resp.get_data(as_text=True)

        # معلّم A: محاولة إدارة صفّ B — 403/404
        resp = teacher_a_client.get(f"/classes/{b['cid']}/lessons/new")
        assert resp.status_code in (403, 404)
        assert secret not in resp.get_data(as_text=True)

        # صفّ A نفسه يبقى متاحاً لطالبه طبيعياً
        assert student_a_client.get(f"/classes/{a['cid']}/lessons").status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# S3 — دورة حياة الاشتراك المدفوع: خطة 850 ILS، دفعتان، تفعيل، رصيد صفر
# ═══════════════════════════════════════════════════════════════════════════


class TestS3PaidSubscriptionLifecycle:
    def test_subscribe_two_payments_approve_activate_zero_balance(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
        from app.services.billing import (
            approve_payment,
            has_active_subscription,
            record_manual_payment,
            subscribe,
            subscription_balance,
        )

        b = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        plan_id = make_subscription_plan(app, b["sid"], b["cid"], name="باقة سنوية كاملة", price=850.0, plan="annual")

        with app.app_context():
            plan = db.session.get(SubscriptionPlan, plan_id)
            sub, err = subscribe(b["students"][0][0], plan, b["cid"])
            assert err is None and sub is not None
            sub_id = sub.id
            sub_row = db.session.get(Subscription, sub_id)
            assert sub_row.status == "pending"
            assert has_active_subscription(b["students"][0][0], b["cid"]) is False

            p1, err = record_manual_payment(sub_row, "إيصال بنكي 4471 – رام الله", "500.00")
            assert err is None and p1 is not None
            approve_payment(db.session.get(ManualPayment, p1.id), reviewer_id=b["admin"][0])
            assert subscription_balance(sub_id) == Decimal("350.00")
            # الاشتراك يُفعّل بعد أول دفعة معتمدة — الباقي على الرصيد
            assert has_active_subscription(b["students"][0][0], b["cid"]) is True

            sub_row = db.session.get(Subscription, sub_id)
            p2, err = record_manual_payment(sub_row, "إيصال بنكي 4482 – رام الله", "350.00")
            assert err is None and p2 is not None
            approve_payment(db.session.get(ManualPayment, p2.id), reviewer_id=b["admin"][0])
            assert subscription_balance(sub_id) == Decimal("0.00")
            approved = ManualPayment.query.filter_by(subscription_id=sub_id, status="approved").all()
            assert [float(p.amount) for p in approved] == [500.00, 350.00]


# ═══════════════════════════════════════════════════════════════════════════
# S4 — كود خصم 15% + شحن محفظة (تسوية إدارية) برصيد دقيق
# ═══════════════════════════════════════════════════════════════════════════


class TestS4DiscountAndWalletCredit:
    def test_discount_code_applied_and_wallet_credited(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
        from app.services.billing import (
            apply_discount_code,
            approve_payment,
            create_discount_code,
            record_manual_payment,
            subscribe,
            subscription_balance,
            validate_discount_code,
        )
        from app.services.wallet_service import admin_credit, get_balance, get_or_create_wallet

        b = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        plan_id = make_subscription_plan(app, b["sid"], b["cid"], name="باقة الفصلين", price=800.0, plan="annual")
        with app.app_context():
            code_row, err = create_discount_code(
                school_id=b["sid"],
                code="AHLA15",
                name="خصم ترحيبي لأهالي رام الله",
                type_="percentage",
                value=15,
                max_uses=5,
            )
        assert err is None and code_row is not None

        with app.app_context():
            discount, err = validate_discount_code("AHLA15", plan_id)
            assert err is None and discount == Decimal("120.00")  # 15% من 800

            plan = db.session.get(SubscriptionPlan, plan_id)
            sub, err = subscribe(b["students"][1][0], plan, b["cid"])
            assert err is None and sub is not None
            sub_id = sub.id

            applied, err = apply_discount_code(sub_id, "AHLA15")
            assert err is None and applied == Decimal("120.00")

            balance = subscription_balance(sub_id)
            assert balance == Decimal("680.00")  # 800 - 120

            sub_row = db.session.get(Subscription, sub_id)
            p, err = record_manual_payment(sub_row, "إيصال 5510 – تسوية بخصم AHLA15", str(balance))
            assert err is None and p is not None
            approve_payment(db.session.get(ManualPayment, p.id), reviewer_id=b["admin"][0])
            assert subscription_balance(sub_id) == Decimal("0.00")

        # المحفظة: إنشاء ثم إيداع إداري 100 ILS برصيد دقيق
        with app.app_context():
            wallet, err = get_or_create_wallet(b["sid"], b["students"][0][0])
            assert err is None and wallet is not None
            tx_row, err = admin_credit(
                school_id=b["sid"],
                target_user_id=b["students"][0][0],
                amount=Decimal("100.00"),
                idempotency_key=f"e2e-credit-{b['students'][0][0]}",
                description="إيداع تجريبي – تسوية دفعة نقدية",
                operator_id=b["admin"][0],
            )
            assert err is None and tx_row is not None
            assert get_balance(b["sid"], b["students"][0][0]) == Decimal("100.00")


# ═══════════════════════════════════════════════════════════════════════════
# S5 — الانتهاء والتجديد: اشتراك منتهٍ ← مهمة الانتهاء ← إعادة اشتراك
# ═══════════════════════════════════════════════════════════════════════════


class TestS5ExpiryAndRenewal:
    def test_expired_subscription_expires_then_renews(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
        from app.services.billing import (
            approve_payment,
            expire_subscriptions,
            has_active_subscription,
            record_manual_payment,
            subscribe,
        )

        b = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        plan_id = make_subscription_plan(app, b["sid"], b["cid"], name="باقة سنوية", price=850.0, plan="annual")
        sub_id = make_subscription(app, b["students"][0][0], plan_id, b["cid"], price=850.0, status="active")
        with app.app_context():

            def _backdate():
                row = db.session.get(Subscription, sub_id)
                row.end_at = datetime.now(UTC) - timedelta(days=3)

            tx(_backdate)
            # القاعدة: الحالة تبقى active حتى تشغيل مهمة الانتهاء الدورية
            assert db.session.get(Subscription, sub_id).status == "active"
            assert has_active_subscription(b["students"][0][0], b["cid"]) is True

        with app.app_context():
            expired_count = expire_subscriptions()
        assert expired_count >= 1
        with app.app_context():
            assert db.session.get(Subscription, sub_id).status == "expired"
            assert has_active_subscription(b["students"][0][0], b["cid"]) is False

            # التجديد: اشتراك جديد ← دفعة ← موافقة ← نشط من جديد
            plan = db.session.get(SubscriptionPlan, plan_id)
            new_sub, err = subscribe(b["students"][0][0], plan, b["cid"])
            assert err is None and new_sub is not None
            p, err = record_manual_payment(new_sub, "إيصال تجديد 4499 – رام الله", "850.00")
            assert err is None and p is not None
            approve_payment(db.session.get(ManualPayment, p.id), reviewer_id=b["admin"][0])
            assert has_active_subscription(b["students"][0][0], b["cid"]) is True


# ═════════════════════════════════════════════════════════════════════
# S6 — المنهج والحضور وبطاقة التقارير
# ═════════════════════════════════════════════════════════════════════


class TestS6AttendanceAndReportCard:
    def test_attendance_statuses_and_report_card(self, app):
        from app.services.gradebook import attendance_summary, record_attendance
        from app.services.report_card import generate_report_card

        b = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        s1, s2, s3 = (b["students"][0][0], b["students"][1][0], None)
        # طالب ثالث غير عضو لا يدخل في الحضور
        s3_uid, _ = _mk_user(app, "student", b["sid"])
        s3 = s3_uid

        today = date.today()
        with app.app_context():
            record_attendance(
                b["cid"],
                today,
                {s1: "present", s2: "late", s3: "absent"},
                recorded_by=b["teacher"][0],
                note="حصة الرياضيات الأولى",
            )
            # تعديل الحالة (upsert): المتأخر تحوّل حاضراً
            record_attendance(b["cid"], today, {s2: "present"}, recorded_by=b["teacher"][0])

            summary_s1 = attendance_summary(b["cid"], s1)
            assert len(summary_s1) == 1
            assert summary_s1[0].status == "present"
            summary_s2 = attendance_summary(b["cid"], s2)
            assert summary_s2[0].status == "present"  # آخر حالة تفوز

        # بطاقة تقارير: فئة + بند + درجات فعلية
        cat_id = make_grade_category(app, b["cid"], "اختبارات الفصل الأول", 100)
        item_id = make_grade_item(app, b["cid"], cat_id, "اختبار الوحدة الأولى", 100)
        make_grade_entry(app, s1, item_id, 85)
        make_grade_entry(app, s2, item_id, 92)

        with app.app_context():
            card = generate_report_card(s1, b["cid"])
            assert isinstance(card, dict) and card
            assert "85" in str(card)


# ═════════════════════════════════════════════════════════════════════
# S7 — دورة اختبار كاملة: MCQ + صح/خطأ + مقالي، خلط لكل محاولة،
#      تصحيح آلي للهدفيات + مراجعة يدوية للمقالي
# ═════════════════════════════════════════════════════════════════════


class TestS7QuizFullLifecycleWithShuffle:
    def test_quiz_three_question_types_shuffle_autograde_manual_essay(self, app):
        from app.extensions import db
        from app.models.assessment import Answer
        from app.services.assessment import (
            add_question,
            create_quiz,
            grade_essay,
            option_index_to_original,
            questions_in_display_order,
            start_attempt,
            submit_attempt,
        )

        b = _school_bundle(app, "مدرسة النور الأساسية – نابلس")
        student_uid = b["students"][0][0]

        with app.app_context():
            quiz, err = create_quiz(
                class_id=b["cid"],
                title="اختبار الوحدة الأولى – الكهرباء الساكنة",
                duration_min=30,
                attempts_allowed=2,
                shuffle=True,
                created_by=b["teacher"][0],
            )
            assert err is None and quiz is not None

            mcq = add_question(
                quiz,
                "mcq",
                "وحدة قياس الشحنة الكهربائية؟",
                options={"items": ["الكولوم", "الأمبير", "الفولت", "الأوم"]},
                correct_answer={"index": 0},
                mark=40,
            )
            tf = add_question(
                quiz,
                "true_false",
                "الشحنات المختلفة تتنافر.",
                correct_answer={"value": False},
                mark=30,
            )
            essay = add_question(
                quiz,
                "essay",
                "اشرح قانون كولوم بأسلوبك مع مثال.",
                mark=30,
            )

            # محاولة 1: الخلط يعيد ترتيباً صحيحاً كاملاً بلا فقد أو تكرار
            a1, err = start_attempt(quiz, student_uid)
            assert err is None and a1 is not None

            order1 = [q.id for q in questions_in_display_order(a1)]
            expected = {mcq.id, tf.id, essay.id}
            assert set(order1) == expected
            assert len(order1) == len(set(order1))

            # خريطة الخيارات المعروضة تعود للفهرس الأصلي بلا تكرار
            shown = [option_index_to_original(mcq, a1, i) for i in range(4)]
            assert sorted(shown) == [0, 1, 2, 3]

            # المحاولة 1: هدفيات صحيحة + مقالي نصي → 70 آلياً ثم 95 بعد المراجعة
            from app.services.assessment import save_answer

            # الفهرس المُرسل من النموذج هو فهرس العرض؛ نجيب بفهرس العرض الذي
            # يطابق الإجابة الصحيحة بعد الترجمة الداخلية للفهرس الأصلي.
            correct_display = shown.index(0)
            save_answer(a1, mcq.id, {"index": correct_display})
            save_answer(a1, tf.id, {"value": False})
            save_answer(
                a1,
                essay.id,
                {
                    "text": "قانون كولوم: القوة تتناسب طردياً مع حاصل ضرب الشحنتين وعكسياً مع مربع المسافة، مثل تنافر كرتين مشحونتين متقابلتين."
                },
            )
            score = submit_attempt(a1)
            assert score == 70.0

            essay_answer = Answer.query.filter_by(attempt_id=a1.id, question_id=essay.id).first()
            grade_essay(essay_answer, 25.0)
            db.session.refresh(a1)
            assert float(a1.score) == 95.0

            # المحاولة 2: بعد تسليم الأولى يُنشأ ترتيب خلط جديد (بذرة attempt_no مختلفة)
            from app.services.assessment import save_answer as _save

            a2, err = start_attempt(quiz, student_uid)
            assert err is None and a2 is not None and a2.id != a1.id
            order2 = [q.id for q in questions_in_display_order(a2)]
            assert set(order2) == expected and len(order2) == len(set(order2))

            # إجابات هدفية خاطئة → صفر آلي
            shown2 = [option_index_to_original(mcq, a2, i) for i in range(4)]
            correct_display2 = shown2.index(0)
            wrong_display2 = (correct_display2 + 1) % len(shown2)
            _save(a2, mcq.id, {"index": wrong_display2})
            _save(a2, tf.id, {"value": True})
            score2 = submit_attempt(a2)
            assert score2 == 0.0

            # قاعدة: لا محاولة ثالثة بعد استنفاد attempts_allowed=2
            a3, err = start_attempt(quiz, student_uid)
            assert a3 is None and err is not None


# ═════════════════════════════════════════════════════════════════════
# S8 — مستخدم فردي + محفظة + جلسة خصوصية + عمولة منصة + تقييم
# ═════════════════════════════════════════════════════════════════════


class TestS8TutoringWalletCommission:
    def test_individual_student_tutor_session_commission_and_rating(self, app):
        from decimal import Decimal

        from app.extensions import db
        from app.models.communication import Notification
        from app.models.wallet import WalletTransaction
        from app.services.tutoring import create_session, get_tutor_earnings, rate_session
        from app.services.wallet_service import (
            TX_TUTOR_COMMISSION,
            admin_credit,
            get_balance,
            get_or_create_wallet,
            process_tutor_commission,
        )

        b = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        student_uid, _ = _mk_user(app, "student", b["sid"])
        individual_uid = make_individual_user(app, school_id=b["sid"])
        tutor_uid, _ = _mk_user(app, "teacher", b["sid"])
        make_tutor_profile(app, tutor_uid, subject="الفيزياء – الصف العاشر", price_hour=120.0)

        # الجلسة: غداً 16:00، 60 دقيقة، 120 ILS
        scheduled = datetime.now(UTC).replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(days=1)
        with app.app_context():
            session_row = create_session(
                tutor_id=tutor_uid,
                student_id=individual_uid,
                subject="الفيزياء – الصف العاشر",
                scheduled_at=scheduled,
                mode="online",
                duration_min=60,
                price=120.0,
            )
            session_id = session_row.id
        assert session_row is not None and session_id

        # المنصة تستلم أجرة الجلسة ثم تحوّلها للمدرّس ثم تخصم العمولة 20%:
        # إيداع إداري للمدرّس 120 (وصول الأجرة) ← خصم عمولة 24 ← رصيد 96
        with app.app_context():
            _wallet, err = get_or_create_wallet(b["sid"], tutor_uid)
            assert err is None
            _platform_wallet, err = get_or_create_wallet(b["sid"], b["admin"][0])
            assert err is None
            _tx, err = admin_credit(
                school_id=b["sid"],
                target_user_id=tutor_uid,
                amount=Decimal("120.00"),
                idempotency_key=f"e2e-session-pay-{session_id}",
                description="أجرة جلسة خصوصية #" + str(session_id),
                operator_id=b["admin"][0],
            )
            assert err is None
            assert get_balance(b["sid"], tutor_uid) == Decimal("120.00")

            result, err = process_tutor_commission(
                school_id=b["sid"],
                tutor_user_id=tutor_uid,
                platform_user_id=b["admin"][0],
                session_amount=Decimal("120.00"),
                commission_rate=Decimal("20"),
                idempotency_key=f"e2e-commission-{session_id}",
                session_id=session_id,
            )
            assert err is None and result is not None
            assert get_balance(b["sid"], tutor_uid) == Decimal("96.00")  # 120 - 24
            assert get_balance(b["sid"], b["admin"][0]) == Decimal("24.00")
            commission_tx = WalletTransaction.query.filter_by(
                transaction_type=TX_TUTOR_COMMISSION, reference_id=session_id
            ).all()
            assert len(commission_tx) >= 1

            earnings = get_tutor_earnings(tutor_uid)
            assert isinstance(earnings, dict)

            # إغلاق الجلسة وتقييمها من الطالب الفردي
            from app.core.db import tx as _tx_fn
            from app.models.tutoring import TutoringSession

            def _complete():
                row = db.session.get(TutoringSession, session_id)
                row.status = "completed"
                row.end_time = scheduled + timedelta(minutes=60)

            _tx_fn(_complete)
            review, err = rate_session(session_id, individual_uid, 5, "شرح ممتاز وسهل")
            assert err is None and review is not None and review.rating == 5


# ═════════════════════════════════════════════════════════════════════
# S9 — واتساب: ربط رقم ← أوامر تفاعلية ← idempotency ← إشعار داخلي
# ═════════════════════════════════════════════════════════════════════


class TestS9WhatsappCommandLifecycle:
    PHONE = "+970591234567"

    def _link(self, app, user_id: int, school_id: int) -> None:
        from datetime import datetime as dt

        from app.extensions import db
        from app.models.whatsapp import WhatsAppLink

        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            db.session.add(
                WhatsAppLink(
                    user_id=user_id,
                    school_id=school_id,
                    phone=self.PHONE,
                    verified_at=dt.now(UTC),
                    is_active=True,
                )
            )
            db.session.commit()

    def test_link_help_and_subscription_commands_with_idempotency(self, app):
        from app.extensions import db
        from app.models.communication import Notification
        from app.services.whatsapp import HELP_TEXT, process_incoming_message

        b = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        student_uid = b["students"][0][0]
        plan_id = make_subscription_plan(app, b["sid"], b["cid"], name="باقة سنوية", price=850.0, plan="annual")
        make_subscription(app, student_uid, plan_id, b["cid"], price=850.0, status="active")
        self._link(app, student_uid, b["sid"])

        with app.app_context():
            with patch("app.services.whatsapp.dispatch_outbound") as dispatch:
                # #مساعدة — قائمة الأوامر
                r1 = process_incoming_message(message_id="wamid.e2e.help", phone=self.PHONE, text="#مساعدة")
                assert r1["status"] == "processed" and HELP_TEXT[:20] in r1["reply"]
                # #اشتراك — حالة الاشتراك + إشعار داخلي مسجّل
                r2 = process_incoming_message(message_id="wamid.e2e.sub", phone=self.PHONE, text="#اشتراك")
                assert r2["status"] == "processed" and r2["reply"]
                # رقم غير مربوط — يُعتر به ردّ مهذب بلا أي بيانات
                r3 = process_incoming_message(message_id="wamid.e2e.stranger", phone="+970599999999", text="#درجات")
                assert r3["status"] == "unlinked"
                # الرسائل الثلاث جميعها تُرسل ردّاً (حتى غير المربوط يُعتر به)
                assert dispatch.call_count == 3

            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            assert Notification.query.filter_by(user_id=student_uid).count() >= 1
            db.session.rollback()

        with app.app_context():
            with patch("app.services.whatsapp.dispatch_outbound") as dispatch2:
                # إعادة إرسال نفس wamid: لا معالجة ثانية ولا إرسال ثاني
                r4 = process_incoming_message(message_id="wamid.e2e.sub", phone=self.PHONE, text="#اشتراك")
                assert r4["status"] == "duplicate" and r4["reply"] == ""
                assert dispatch2.call_count == 0


# ═════════════════════════════════════════════════════════════════════
# S10 — AI: حصة معطّلة للمدرسة + سقف استهلاك مستنفد → رفض مهذب
# ═════════════════════════════════════════════════════════════════════


class TestS10AiQuotaFallback:
    def test_ai_disabled_and_quota_exhausted_fail_gracefully(self, app):
        from app.extensions import db
        from app.models.content import Lesson
        from app.models.tenant import TenantQuota

        b = _school_bundle(app, "مدرسة النور الأساسية – نابلس")
        lesson_id = make_lesson(app, b["cid"], title="درس التيار المستمر")

        with app.app_context():
            # حصة معطّلة كلياً للمدرسة (free tier الافتراضي: ai_enabled=False، سقف 0)
            quota = TenantQuota.query.filter_by(school_id=b["sid"]).first()
            if quota is None:
                quota = TenantQuota(school_id=b["sid"], tier="free")
                db.session.add(quota)
                db.session.commit()

        teacher_client = _login(app, b["teacher"][1])
        resp = teacher_client.post("/ai/quiz/generate", json={"lesson_id": lesson_id})
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["error"]["code"] in ("AI_DISABLED_FOR_TENANT", "AI_QUOTA_EXCEEDED")

        # سقف مستنفد: ai_enabled=True لكن max=0 — وأبطل كاش الحصة (30ث) أولاً
        from app.core.permissions import invalidate_ai_quota_cache

        invalidate_ai_quota_cache(b["sid"])
        with app.app_context():
            quota = TenantQuota.query.filter_by(school_id=b["sid"]).first()
            quota.ai_enabled = True
            quota.max_ai_tokens_monthly = 0
            db.session.commit()
        invalidate_ai_quota_cache(b["sid"])

        teacher_client = _login(app, b["teacher"][1])
        resp2 = teacher_client.post("/ai/quiz/generate", json={"lesson_id": lesson_id})
        assert resp2.status_code == 403
        assert resp2.get_json()["error"]["code"] == "AI_QUOTA_EXCEEDED"

        # الدرس نفسه سليم وغير مساس بفشل AI
        with app.app_context():
            assert db.session.get(Lesson, lesson_id) is not None


# ═════════════════════════════════════════════════════════════════════
# S11 — RLS fail-closed: بلا سياق تينانتس = صفر صفوف، ومع platform_scope = الكل
# ═════════════════════════════════════════════════════════════════════


class TestS11RlsFailClosed:
    def test_missing_context_denies_and_platform_scope_allows(self, app):
        from sqlalchemy import text

        from app.core.rls import platform_scope
        from app.extensions import db
        from app.models.class_room import ClassRoom
        from app.models.user import User

        a = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        b = _school_bundle(app, "مدرسة النور الأساسية – نابلس")
        total = 2

        with app.app_context():
            # تصفير السياق: بلا GUCs لا يرى azad_app أي صفّ صفوف (fail-closed)
            db.session.rollback()
            db.session.execute(
                text(
                    "SELECT set_config('app.current_user_id', '0', true), "
                    "set_config('app.current_school_id', '0', true), "
                    "set_config('app.is_super_admin', '0', true), "
                    "set_config('app.current_class_ids', '', true)"
                )
            )
            visible_rows = db.session.execute(text("SELECT count(*) FROM classes")).scalar()
            assert int(visible_rows) == 0
            db.session.rollback()

            # عبر platform_scope (قراءة منصة مقيّدة) ترجع الصفوف كلها
            with platform_scope():
                assert ClassRoom.query.count() >= total
            db.session.rollback()

        # والتطبيق التشغيلي: مستخدم عادي يرى مدرسته فقط عبر GUCs الطلبية
        client = _login(app, a["teacher"][1])
        resp = client.get(f"/classes/{a['cid']}/lessons")
        assert resp.status_code == 200
        client_b = _login(app, b["teacher"][1])
        resp2 = client_b.get(f"/classes/{a['cid']}/lessons")
        assert resp2.status_code in (403, 404)

        # المستخدمون موجودون فعلاً (لم يحذف الفشل شيئاً) — تحقق ختامي
        with app.app_context():
            with platform_scope():
                assert User.query.count() >= 4


# ═════════════════════════════════════════════════════════════════════
# S12 — ملخص مالي: دفعتان معتمدتان + دفعة مرفوضة = الحساب الصحيح فقط
# ═════════════════════════════════════════════════════════════════════


class TestS12MultiPaymentSummaryWithRejection:
    def test_approved_rejected_payments_summary_math(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
        from app.services.billing import (
            approve_payment,
            reject_payment,
            record_manual_payment,
            subscription_balance,
            subscribe,
        )

        b = _school_bundle(app, "مدرسة الأمل الثانوية – رام الله")
        plan_id = make_subscription_plan(
            app, b["sid"], b["cid"], name="باقة سنوية – مرحلة أولى", price=850.0, plan="annual"
        )

        with app.app_context():
            plan = db.session.get(SubscriptionPlan, plan_id)
            sub, err = subscribe(b["students"][0][0], plan, b["cid"])
            assert err is None and sub is not None
            sub_id = sub.id

            sub_row = db.session.get(Subscription, sub_id)
            p_ok1, err = record_manual_payment(sub_row, "إيصال 5601 – رام الله", "300.00")
            assert err is None
            approve_payment(db.session.get(ManualPayment, p_ok1.id), reviewer_id=b["admin"][0])

            sub_row = db.session.get(Subscription, sub_id)
            p_bad, err = record_manual_payment(sub_row, "إيصال 5602 – شيك مرتجع", "200.00")
            assert err is None
            reject_payment(db.session.get(ManualPayment, p_bad.id))

            sub_row = db.session.get(Subscription, sub_id)
            p_ok2, err = record_manual_payment(sub_row, "إيصال 5603 – رام الله", "250.00")
            assert err is None
            approve_payment(db.session.get(ManualPayment, p_ok2.id), reviewer_id=b["admin"][0])

            # الحساب: 850 - (300 + 250) = 300 — المرفوض لا يُخصم أبداً
            assert subscription_balance(sub_id) == Decimal("300.00")
            approved = ManualPayment.query.filter_by(subscription_id=sub_id, status="approved").all()
            rejected = ManualPayment.query.filter_by(subscription_id=sub_id, status="rejected").all()
            assert sum(float(p.amount) for p in approved) == 550.0
            assert [float(p.amount) for p in rejected] == [200.0]
