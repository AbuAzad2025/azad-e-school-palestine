from datetime import UTC, datetime

from app.core.tenancy import current_school_id
from app.models.user import UserRole
from app.services.schools import is_member


def parent_has_active_member(parent_id: int, class_id: int) -> bool:
    """هل لولي الأمر طالب واحد على الأقل عضو فعّال في هذا الصف؟

    كان التنفيذ ``is_parent_of`` داخل حلقة على كل عضو بالصف (N استعلامات لـ
    N طلاب)؛ نتحقق الآن بوجود رابط أسرة نشط واحد فقط باستعلام واحد.
    """
    from app.models.class_room import ClassMember
    from app.models.family import FamilyLink

    return (
        FamilyLink.query.join(
            ClassMember,
            ClassMember.user_id == FamilyLink.student_id,
        )
        .filter(
            FamilyLink.parent_id == parent_id,
            FamilyLink.status == "active",
            ClassMember.class_id == class_id,
            ClassMember.status == "active",
        )
        .first()
        is not None
    )


def _is_class_free(class_room) -> bool:
    """Check if a class is free (no paid SubscriptionPlan)."""
    from decimal import Decimal

    from app.models.billing import SubscriptionPlan

    plan = SubscriptionPlan.query.filter_by(class_id=class_room.id, is_active=True).first()
    if not plan:
        return True
    return Decimal(str(plan.price)) <= 0


def _has_valid_subscription(user_id: int, class_id: int) -> bool:
    """Check if user has an active, non-expired subscription for a class."""
    from app.models.billing import Subscription

    now = datetime.now(UTC)
    sub = Subscription.query.filter_by(user_id=user_id, class_id=class_id, status="active").first()
    if not sub:
        return False
    # P-SEC-10: تحقق من انتهاء الصلاحية
    if sub.end_at and sub.end_at < now:
        return False
    return True


def paid_plan_for(class_room):
    """الخطة النشطة المدفوعة لصف، أو لا شيء (صف مجاني/بلا خطة) — AZ-P0-02.

    تعريف واحد مشترك لـ «صف يتطلب دفعاً»: مسارة join_class تحتاجه لإرفاق رابط
    الحلقة الدفع في رسالة الرفض، بلا تكرار منطق السعر عند كل مستهلك.
    """
    from decimal import Decimal

    from app.models.billing import SubscriptionPlan

    plan = SubscriptionPlan.query.filter_by(class_id=class_room.id, is_active=True).first()
    if plan and Decimal(str(plan.price)) > 0:
        return plan
    return None


def can_view_class(class_room, user) -> bool:
    """Determine if a user can view class content.

    P-SEC-11: super_admin و school_admin/teacher يحصلون على وصول كامل.
    P-SEC-12: الصفوف المجانية — العضوية كافية.
    P-SEC-13: الصفوف المدفوعة — يجب اشتراك نشط غير منتهي.
    """
    # P-SEC-11: إدارة علوية — وصول كامل دائماً
    if user.role == UserRole.super_admin:
        return True
    if current_school_id() == class_room.school_id and user.role in (UserRole.school_admin, UserRole.teacher):
        return True

    # P-SEC-14: وليّ الأمر — إشراف قراءة فقط على صفوف أبنائه.
    # نموذج الربط الفعلي: وليّ الأمر عضو نشط في صفّ ابنه، أو مرتبط عبر FamilyLink
    # بطالب عضو نشط. الصلاحية مشتقة من عضوية الابن نفسه. وليّ الأمر بلا رابط
    # مدرسة فيُقيَّد بـ RLS عن صفّ المدرسة نفسه، لذا كلا استعلامي الإثبات
    # هنا يمرّان عبر قراءة مرفوعة مقيّدة — تعيدان عضوية ابنه فقط ولا تكشفان
    # شيئاً عن صفّ غير صفّه (فلترة class_id تبقى في WHERE).
    if user.role == UserRole.parent:
        from app.core.rls import access_read_scope
        from app.models.class_room import ClassMember
        from app.models.family import FamilyLink

        with access_read_scope("class_members", class_room.id):
            # استعلام إثبات واحد: عضوية وليّ الأمر نفسه، أو عضوية ابنٍ مرتبط
            # به عبر FamilyLink نشط. (P2-PERF: ثابت مهما كثر أبناء الصف.)
            return (
                ClassMember.query.outerjoin(
                    FamilyLink,
                    (FamilyLink.student_id == ClassMember.user_id)
                    & (FamilyLink.parent_id == user.id)
                    & (FamilyLink.status == "active"),
                )
                .filter(
                    ClassMember.class_id == class_room.id,
                    ClassMember.status == "active",
                    (ClassMember.user_id == user.id) | FamilyLink.id.isnot(None),
                )
                .first()
                is not None
            )

    # P-SEC-12: الصف مجاني — العضوية كافية
    if _is_class_free(class_room):
        return is_member(class_room, user)

    # P-SEC-13: الصف مدفوع — يجب اشتراك نشط غير منتهي
    return _has_valid_subscription(user.id, class_room.id)


def can_teach_class(class_room, user) -> bool:
    if user.role == UserRole.super_admin:
        return True
    if user.role == UserRole.school_admin:
        return current_school_id() == class_room.school_id
    return class_room.teacher_id == user.id


def can_pay_class(class_room, user) -> bool:
    """أهلية فتح *صفحة الدفع* لصف لكن لا محتواه (AZ-P0-01).

    الطالب الفرد المشترك في كورس عام مدفوع يحمل اشتراكاً ``pending``: لا عضوية
    فعّالة فيقف ``can_view_class`` عندها (P-SEC-13 صحيح للمحتوى ويبقى)، لكن
    حاجبه لصفحة الدفع كان يدفعه لـ 403 فتنغلق حلقة الدفع ذاتياً. ذراع الاشتراك
    هنا مقيدة بمعرفي الفاعل والصف معاً — فصاحب اشتراك مدرسة أخرى يظل مخفياً
    بـ RLS والذراع لا تراه أصلاً.

    AZ-P0-03: وليّ الأمر المرتبط يفتح صفحة الدفع لصفّ ابنه — حاجبه كان يغلق
    حلقة «الدفع من الأسرة» كاملةً من بابها الأول. الذراع مقيدة بأبنائه
    المرتبطين (رابط نشط) فقط: اشتراك أي طالب آخر في الصف لا يفتح له الباب،
    وقراءة رابط الأسرة كذلك مقيدة بالوالدين المُمثَّلين في الاستعلام.
    """
    if can_view_class(class_room, user):
        return True
    if user.role == UserRole.parent:
        return _parent_can_pay(class_room.id, user.id)
    if user.role != UserRole.student:
        return False
    from app.models.billing import Subscription

    return Subscription.query.filter_by(user_id=user.id, class_id=class_room.id).first() is not None


def _parent_can_pay(class_id: int, parent_id: int) -> bool:
    """أبناء مرتبطون (رابط نشط) لهم اشتراك في الصف أو عضوية فعّالة فيه.

    عضوية فعّالة تكفي حتى قبل إنشاء الاشتراك — وليّ الأمر يستطيع فتح صفحة
    الدفع والاشتراك لابنه من هناك. الاستعلامان ذراعان بمعرّف الوالد فلا
    يكشفان طلباً لأسرة أخرى ولا معلومات أبناء غيره.
    """
    from app.models.billing import Subscription
    from app.models.class_room import ClassMember
    from app.models.family import FamilyLink

    linked_children = FamilyLink.query.filter_by(parent_id=parent_id, status="active").all()
    student_ids = [link.student_id for link in linked_children]
    if not student_ids:
        return False
    has_subscription = (
        Subscription.query.filter(
            Subscription.user_id.in_(student_ids),
            Subscription.class_id == class_id,
        ).first()
        is not None
    )
    if has_subscription:
        return True
    return (
        ClassMember.query.filter(
            ClassMember.user_id.in_(student_ids),
            ClassMember.class_id == class_id,
            ClassMember.status == "active",
        ).first()
        is not None
    )
