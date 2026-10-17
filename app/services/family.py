"""خدمات روابط الأسرة — ربط ولي الأمر بالطالب."""

import secrets
from datetime import UTC, datetime, timedelta

from app.core.db import tx
from app.core.i18n import _
from app.extensions import db
from app.models.family import FamilyLink, FamilyLinkCode
from app.models.user import User, UserRole


def generate_link_code(student_id: int) -> tuple[str | None, str | None]:
    """ينشئ رمز ربط جديد للطالب (8 أحرف) — صلاحية 24 ساعة."""
    student = db.session.get(User, student_id)
    if not student or student.role != UserRole.student:
        return None, _("المستخدم ليس طالباً.")

    code = secrets.token_urlsafe(6)[:8].upper()
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    def _create():
        # إلغاء الرموز القديمة
        FamilyLinkCode.query.filter_by(student_id=student_id, used=False).update({"used": True})
        flc = FamilyLinkCode(student_id=student_id, code=code, expires_at=expires_at)
        db.session.add(flc)
        return flc

    result = tx(_create)
    return result.code if result else None, None


def link_parent(parent_id: int, code: str) -> tuple[FamilyLink | None, str | None]:
    """يربط ولي الأمر بالطالب عبر الرمز."""
    code = (code or "").strip().upper()
    if not code:
        return None, _("الرمز مطلوب.")

    parent = db.session.get(User, parent_id)
    if not parent or parent.role != UserRole.parent:
        return None, _("المستخدم ليس ولي أمر.")

    link_code = FamilyLinkCode.query.filter_by(code=code, used=False).first()
    if not link_code:
        return None, _("الرمز غير صالح أو مستخدم مسبقاً.")

    # تحقق من انتهاء الصلاحية
    if link_code.expires_at and link_code.expires_at < datetime.now(UTC):
        return None, _("انتهت صلاحية الرمز.")

    # منع ربط الطالب بنفسه
    if link_code.student_id == parent_id:
        return None, _("لا يمكن ربط الحساب بنفسه.")

    existing = FamilyLink.query.filter_by(parent_id=parent_id, student_id=link_code.student_id, status="active").first()
    if existing:
        return None, _("أنت مرتبط بهذا الطالب مسبقاً.")

    def _link():
        link_code.used = True
        link_code.used_by = parent_id
        link = FamilyLink(
            parent_id=parent_id,
            student_id=link_code.student_id,
            status="active",
        )
        db.session.add(link)
        return link

    return tx(_link), None


def list_children(parent_id: int) -> list[FamilyLink]:
    """يُعيد قائمة الأبناء المرتبطين بولي الأمر مع بيانات الطلاب."""
    from sqlalchemy.orm import joinedload

    return (
        FamilyLink.query.options(joinedload(FamilyLink.student)).filter_by(parent_id=parent_id, status="active").all()
    )


def remove_link(link_id: int, parent_id: int) -> tuple[bool, str | None]:
    """يزيل رابط ولي أمر بالطالب."""
    link = db.session.get(FamilyLink, link_id)
    if not link or link.parent_id != parent_id:
        return False, _("الرابط غير موجود.")

    def _remove():
        link.status = "removed"

    tx(_remove)
    return True, None


def is_parent_of(parent_id: int, student_id: int) -> bool:
    """يتحقق مما إذا كان ولي الأمر مرتبطاً بالطالب."""
    return FamilyLink.query.filter_by(parent_id=parent_id, student_id=student_id, status="active").first() is not None


def child_progress_summary(student_id: int) -> list[dict]:
    """AZ-P2-11 — ملخص تقدم الطالب لكل صف من صفوفه.

    ثلاث أبعاد على النماذج الموجودة: نسبة إنجاز الدروس المنشورة
    (Lesson/StudentProgress)، متوسط الدرجات (GradeEntry مع max_mark
    للبند)، والحضور الزمني (Attendance: حاضر/غائب/متأخر).

    استعلامات مجمّعة (بلا N+1). غياب البيانات يُعاد ``None`` — لا صفر
    مضلّل: الصفوب بلا دروس يعرض حالة فراغ صريحة في الواجهة.
    """
    from sqlalchemy import func, select
    from sqlalchemy.orm import joinedload

    from app.models.attendance import Attendance
    from app.models.class_room import ClassMember
    from app.models.content import Lesson
    from app.models.gradebook import GradeEntry, GradeItem
    from app.models.progress import StudentProgress

    memberships = (
        ClassMember.query.filter_by(user_id=student_id, status="active")
        .options(joinedload(ClassMember.class_room))
        .all()
    )
    class_ids = [m.class_id for m in memberships]
    if not class_ids:
        return []

    rows: dict[int, dict] = {m.class_id: {"class_room": m.class_room} for m in memberships}

    # 1) إجمالي الدروس المنشورة لكل صف
    lesson_totals: dict[int, int] = {
        int(cid): int(cnt)
        for cid, cnt in db.session.execute(
            select(Lesson.class_id, func.count())
            .where(Lesson.class_id.in_(class_ids), Lesson.status == "published")
            .group_by(Lesson.class_id)
        ).all()
    }

    # 2) الدروس المكتملة للطالب لكل صف
    completed_totals: dict[int, int] = {
        int(cid): int(cnt)
        for cid, cnt in db.session.execute(
            select(StudentProgress.class_id, func.count())
            .where(
                StudentProgress.student_id == student_id,
                StudentProgress.class_id.in_(class_ids),
                StudentProgress.status == "completed",
            )
            .group_by(StudentProgress.class_id)
        ).all()
    }

    # 3) معدل الدرجات لكل صف — مجموع الدرجات / مجموع العلامات الكاملة
    grade_sums: dict[int, tuple[float, float]] = {
        int(cid): (float(sum_mark), float(sum_max))
        for cid, sum_mark, sum_max in db.session.execute(
            select(GradeItem.class_id, func.sum(GradeEntry.mark), func.sum(GradeItem.max_mark))
            .join(GradeEntry, GradeEntry.grade_item_id == GradeItem.id)
            .where(
                GradeEntry.student_id == student_id,
                GradeItem.class_id.in_(class_ids),
                GradeEntry.mark.is_not(None),
                GradeItem.max_mark.is_not(None),
            )
            .group_by(GradeItem.class_id)
        ).all()
    }

    # 4) الحضور لكل (صف، حالة)
    att_by_class: dict[int, dict[str, int]] = {}
    for cid, status, count in db.session.execute(
        select(Attendance.class_id, Attendance.status, func.count())
        .where(Attendance.student_id == student_id, Attendance.class_id.in_(class_ids))
        .group_by(Attendance.class_id, Attendance.status)
    ).all():
        att_by_class.setdefault(int(cid), {})[str(status)] = int(count)

    for cid, row in rows.items():
        total = int(lesson_totals.get(cid, 0))
        completed = int(completed_totals.get(cid, 0))
        sums = grade_sums.get(cid)
        att = att_by_class.get(cid)
        row["lessons_total"] = total
        row["lessons_completed"] = completed if total else 0
        row["completion_pct"] = round(completed * 100 / total) if total else None
        if sums and sums[1] > 0:
            row["avg_grade_pct"] = round(sums[0] * 100 / sums[1], 1)
        else:
            row["avg_grade_pct"] = None
        # غياب أي سجل حضور → لا أرقام مضللة، حالة فراغ صريحة.
        if att:
            present = att.get("present", 0)
            row["attendance"] = {
                "present": present,
                "absent": att.get("absent", 0),
                "late": att.get("late", 0),
                "excused": att.get("excused", 0),
            }
        else:
            row["attendance"] = None
    return list(rows.values())


def get_parent(student_id: int) -> User | None:
    """يُعيد ولي الأمر الأول للطالب."""
    link = FamilyLink.query.filter_by(student_id=student_id, status="active").first()
    if link:
        return db.session.get(User, link.parent_id)
    return None


def billing_by_student(parent_id: int) -> dict[int, list[dict]]:
    """كشف حساب الأسرة — اشتراكات كل ابن مع رصيد المتبقي (AZ-P0-03).

    القيم:exprybط مقيدة بأبناء وليّ الأمر المرتبطين برابط نشط:
    استعلام الاشتراكات بـ ``user_id IN (أبنائنا)`` فحساب لا يظهر فيه
    طلب أسرة أخرى. الأرصدة تُشتق في استعلامين لا استعلام لكل اشتراك.

    يعيد ``{student_id: [entry, ...]}`` حيث كل entry:
    ``subscription`` (مع class_room وplan محمّلين)، ``balance`` (Decimal)،
    و``approved_count`` (عدد الدفعات المعتمدة — لرابط الفاتورة).
    """
    from sqlalchemy import func, select
    from sqlalchemy.orm import joinedload

    from app.models.billing import ManualPayment, Subscription
    from app.services import billing

    links = list_children(parent_id)
    student_ids = [link.student_id for link in links]
    if not student_ids:
        return {}

    subs = (
        Subscription.query.options(
            joinedload(Subscription.plan),
            joinedload(Subscription.class_room),
        )
        .filter(Subscription.user_id.in_(student_ids))
        .order_by(Subscription.created_at.desc())
        .all()
    )
    if not subs:
        return {}
    sub_ids = [sub.id for sub in subs]
    balances = billing.subscription_balances(sub_ids)
    approved_counts: dict[int, int] = {}
    for sid, count in db.session.execute(
        select(ManualPayment.subscription_id, func.count())
        .where(ManualPayment.subscription_id.in_(sub_ids), ManualPayment.status == "approved")
        .group_by(ManualPayment.subscription_id)
    ).all():
        approved_counts[int(sid)] = int(count)
    by_student: dict[int, list[dict]] = {}
    for sub in subs:
        by_student.setdefault(sub.user_id, []).append(
            {
                "subscription": sub,
                "balance": balances.get(sub.id, sub.price),
                "approved_count": approved_counts.get(sub.id, 0),
            }
        )
    return by_student
