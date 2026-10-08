#!/usr/bin/env python3
"""Deterministic E2E fixture — real journeys for Playwright, no mocks of our own app.

Why this exists: the E2E job runs against an empty Postgres, so an
authenticated journey (login -> dashboard -> attendance -> invoice) had
nothing to assert on. Seeding the app's own data through its own models
keeps the suite honest: no stubbed endpoints, no UI-only fake state.

Idempotent: re-running reuses the existing tenant and accounts instead of
duplicating them, so a retried CI job stays stable.

Atomicity: every write goes through ``tx(...)`` like the rest of the
codebase (AGENTS.md) — one commit per unit of work, rollback on error.

Accounts live under ``e2e.example.com`` (RFC 2606): ``.test`` is a special-use
name that WTForms' ``Email()`` validator rejects outright, so a seed address there
would make every login test fail on validation rather than on behaviour.

Credentials come from the environment (D4 — nothing secret is committed):
    E2E_PASSWORD   password for every seeded account
    E2E_EMAIL      parent account used by the specs (default: parent@e2e.example.com)

A row-id manifest is written to ``E2E_SEED_FILE`` (default
``tests/e2e/.seed.json``) so the Playwright specs address real rows instead of
guessing ids. It holds identifiers only — never the password.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from app.core.db import tx  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.attendance import Attendance  # noqa: E402
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan  # noqa: E402
from app.models.class_room import ClassMember, ClassRoom  # noqa: E402
from app.models.content import Lesson, Unit  # noqa: E402
from app.models.family import FamilyLink  # noqa: E402
from app.models.gradebook import GradeCategory, GradeEntry, GradeItem  # noqa: E402
from app.models.school import Grade, School, Subject  # noqa: E402
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink  # noqa: E402
from app.models.whatsapp import WhatsAppLink  # noqa: E402

SCHOOL_DOMAIN = "e2e-school.example.com"
TEACHER_EMAIL = "teacher@e2e.example.com"
PARENT_EMAIL = os.getenv("E2E_EMAIL", "parent@e2e.example.com")
STUDENT_EMAIL = "student@e2e.example.com"
#: رقم E.164 مرتبط بولي الأمر — يسمح للاختبار بإرسال رسالة موقّعة بوصفه مُربَّطاً.
PARENT_PHONE = "+970590000001"
PLAN_PRICE = Decimal("500.00")
#: Manifest of row ids for the specs. No credentials, no secrets.
SEED_MANIFEST = os.getenv(
    "E2E_SEED_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "e2e", ".seed.json")),
)

T = TypeVar("T")

# The seeder writes across every tenant boundary at once, so it runs as a
# super-admin. RLS is FORCEd on these tables, which means even the table
# owner is filtered — the bypass has to be set on the *connection*, not with
# SET LOCAL, or it would evaporate at the first commit.
BYPASS_RLS_SQL = "SELECT set_config('app.is_super_admin', '1', false), set_config('app.current_school_id', '0', false)"


def _bypass_rls() -> None:
    """Pin the super-admin RLS variables onto every pooled DBAPI connection."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        previous = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            with dbapi_connection.cursor() as cur:
                cur.execute(BYPASS_RLS_SQL)
        finally:
            dbapi_connection.autocommit = previous


def _save(obj: T) -> T:
    """Persist one object through tx() and return it with a usable identity."""
    tx(db.session.add, obj)
    db.session.flush()
    return obj


def _user(email: str, role: UserRole, school_id: int, password: str) -> User:
    existing = User.query.filter_by(email=email).first()
    if existing is not None:
        # Re-seeding with a different E2E_PASSWORD must take effect: keeping the
        # stale hash made every login fail with "invalid credentials" instead of
        # surfacing the mismatch, and left a deactivated account unusable.
        existing.password_hash = hash_password(password)
        existing.approval_status = UserApprovalStatus.approved
        existing.is_active = True
        existing.is_verified = True
        tx(db.session.flush)
        if not UserRoleLink.query.filter_by(user_id=existing.id, school_id=school_id, role=role).first():
            _save(
                UserRoleLink(
                    user_id=existing.id,
                    school_id=school_id,
                    role=role,
                    is_active=True,
                )
            )
        return existing
    user = User(
        email=email,
        name_ar=_display_name(role),
        role=role,
        password_hash=hash_password(password),
        approval_status=UserApprovalStatus.approved,
        is_active=True,
        is_verified=True,
    )
    _save(user)
    _save(
        UserRoleLink(
            user_id=user.id,
            school_id=school_id,
            role=role,
            is_active=True,
        )
    )
    return user


def _display_name(role: UserRole) -> str:
    return {
        UserRole.teacher: "معلمة الاختبارات",
        UserRole.parent: "ولي أمر E2E",
        UserRole.student: "طالب E2E",
    }.get(role, "مستخدم E2E")


def _seed(password: str) -> tuple[dict[str, int], str]:
    school = School.query.filter_by(domain=SCHOOL_DOMAIN).first()
    if school is None:
        school = _save(School(name_ar="مدرسة E2E", domain=SCHOOL_DOMAIN, is_active=True))
    school_id = school.id

    grade = Grade.query.filter_by(school_id=school_id, grade_level=1).first()
    if grade is None:
        grade = _save(Grade(school_id=school_id, grade_level=1, name_ar="الصف الأول", stage="primary"))

    subject = Subject.query.filter_by(code="E2E-MATH").first()
    if subject is None:
        subject = _save(Subject(code="E2E-MATH", name_ar="رياضيات", name_en="Mathematics"))

    teacher = _user(TEACHER_EMAIL, UserRole.teacher, school_id, password)
    parent = _user(PARENT_EMAIL, UserRole.parent, school_id, password)
    student = _user(STUDENT_EMAIL, UserRole.student, school_id, password)

    # join_code فريد عالمياً؛ اشتقاقه من مدرسة البذرة يمنع التصادم
    # عبر المستأجرين ويبقي إعادة التشغيل عديمة الأثر.
    join_code = f"E2EJOIN{school_id}"
    class_room = ClassRoom.query.filter_by(school_id=school_id, join_code=join_code).first()
    if class_room is None:
        class_room = _save(
            ClassRoom(
                school_id=school_id,
                subject_id=subject.id,
                grade_id=grade.id,
                teacher_id=teacher.id,
                name="صف E2E",
                join_code=join_code,
                is_active=True,
                currency="ILS",
                price_annual=PLAN_PRICE,
            )
        )
    class_id = class_room.id

    # الطالب ووليّ الأمر كلاهما عضو نشط: العضوية هي ما يفتح لوليّ الأمر
    # صف ابنه (P-SEC-14) وما يسمح له بفتح الفاتورة (is_member).
    for member in (student, parent):
        if not ClassMember.query.filter_by(class_id=class_id, user_id=member.id).first():
            _save(ClassMember(class_id=class_id, user_id=member.id, status="active"))

    if not FamilyLink.query.filter_by(parent_id=parent.id, student_id=student.id).first():
        _save(FamilyLink(parent_id=parent.id, student_id=student.id, status="active"))

    today = date.today()
    attendance_rows = Attendance.query.filter_by(class_id=class_id, student_id=student.id, date=today).all()
    if not attendance_rows:
        _save(
            Attendance(
                class_id=class_id,
                student_id=student.id,
                date=today,
                status="present",
                note="حضور مسجَّل مسبقاً",
                recorded_by=teacher.id,
            )
        )
    else:
        # إعادة التهيئة تعيد المزامنة إلى القيم المزروعة وتنظف المكررات:
        # اختبارات سابقة (خاصة اختبار تعديل المعلم الذي قد يُقتل في منتصف
        # مهلته دون أن يكمل استرجاعه) تلوّث الصف أو تضاعفه — والمخطط بلا
        # قيد تفرد (class_id, student_id, date) فالسويت الحتمي هو الضمانة.
        attendance_rows[0].status = "present"
        attendance_rows[0].note = "حضور مسجَّل مسبقاً"
        for extra in attendance_rows[1:]:
            db.session.delete(extra)
        _save(attendance_rows[0])

    unit = Unit.query.filter_by(class_id=class_id).first()
    if unit is None:
        unit = _save(Unit(class_id=class_id, title="الوحدة الأولى", sort_order=1))

    lesson = Lesson.query.filter_by(class_id=class_id, unit_id=unit.id).first()
    if lesson is None:
        _save(
            Lesson(
                class_id=class_id,
                unit_id=unit.id,
                title="درس E2E",
                body_html="<p>محتوى تجريبي للاختبار الآلي</p>",
                status="published",
                created_by=teacher.id,
            )
        )

    category = GradeCategory.query.filter_by(class_id=class_id, name="الاختبارات").first()
    if category is None:
        category = _save(GradeCategory(class_id=class_id, name="الاختبارات", weight=Decimal("100")))

    item = GradeItem.query.filter_by(class_id=class_id, title="اختبار قصير").first()
    if item is None:
        item = _save(
            GradeItem(
                class_id=class_id,
                category_id=category.id,
                title="اختبار قصير",
                max_mark=Decimal("100"),
                kind="exam",
            )
        )

    if not GradeEntry.query.filter_by(student_id=student.id, grade_item_id=item.id).first():
        _save(
            GradeEntry(
                student_id=student.id,
                grade_item_id=item.id,
                mark=Decimal("88"),
                recorded_by=teacher.id,
                note="أداء متقن",
            )
        )

    # النطاق يشمل الصف: اسم الخطة غير فريد، وصفحة الدفع تسرد خطط صفّها فقط.
    plan = SubscriptionPlan.query.filter_by(school_id=school_id, class_id=class_id, name="خطة E2E").first()
    if plan is None:
        plan = _save(
            SubscriptionPlan(
                school_id=school_id,
                class_id=class_id,
                name="خطة E2E",
                plan="annual",
                price=PLAN_PRICE,
                currency="ILS",
                duration_days=365,
                is_active=True,
            )
        )

    subscription = Subscription.query.filter_by(user_id=student.id, class_id=class_id).first()
    if subscription is None:
        now = datetime.now(UTC)
        subscription = _save(
            Subscription(
                user_id=student.id,
                plan_id=plan.id,
                class_id=class_id,
                price=PLAN_PRICE,
                currency="ILS",
                status="active",
                source="manual",
                start_at=now - timedelta(days=10),
                end_at=now + timedelta(days=350),
            )
        )
        _save(
            ManualPayment(
                subscription_id=subscription.id,
                reference="E2E-REF-0001",
                amount=PLAN_PRICE,
                note="دفعة تجريبية",
                status="approved",
                gateway="manual",
                reviewed_by=teacher.id,
            )
        )

    if not WhatsAppLink.query.filter_by(phone=PARENT_PHONE).first():
        _save(
            WhatsAppLink(
                user_id=parent.id,
                school_id=school_id,
                phone=PARENT_PHONE,
                is_active=True,
                verified_at=datetime.now(UTC),
            )
        )

    ids = {
        "school_id": school_id,
        "class_id": class_id,
        "student_id": student.id,
        "subscription_id": subscription.id,
        "grade_item_id": item.id,
    }
    return ids, join_code


def main() -> int:
    password = os.getenv("E2E_PASSWORD")
    if not password:
        print("E2E_PASSWORD is required (D4: no secrets in the repository).", file=sys.stderr)
        return 2

    app = create_app()
    with app.app_context():
        _bypass_rls()
        ids, join_code = _seed(password)
        manifest = {
            **ids,
            "join_code": join_code,
            "parent_email": PARENT_EMAIL,
            "student_email": STUDENT_EMAIL,
            "teacher_email": TEACHER_EMAIL,
            "parent_phone": PARENT_PHONE,
        }
        with open(SEED_MANIFEST, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
        print(
            "E2E seed ready: "
            f"school={ids['school_id']} class={ids['class_id']} "
            f"subscription={ids['subscription_id']} parent={PARENT_EMAIL}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
