"""Centralized API tenancy helpers for API v1 routes.

يُستخدم هذا الوحدة كمرجع واحد لتحديد نطاق المدرسة الخاصة
بالمستخدم الحالي وتطبيق فحوصات الوصول المشتركة على 엔드포인트ات
الـ API، بدلاً من تكرار نفس المنطق يدوياً في كل مسار.

القواعد الأساسية:
- super_admin لا يخضع لحدود مدرسة واحدة.
- school_admin يصل فقط إلى مدرسته المخصصة.
- غير المخوّلين بهذه الصلاحيات يصلون إما إلى مدارسهم عبر
  الاشتراكات/العضويات أو إلى الصفوف/الدروس/المستخدمين المرتبطين
  بهم مباشرة.
"""

from __future__ import annotations

from typing import Any

from flask import abort
from flask_login import current_user

from app.core.tenancy import current_school_id
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.school import School
from app.models.user import User, UserRole, UserRoleLink


def current_user_school_id() -> int | None:
    """مدرسة المستخدم الحالي المباشرة، أو None إذا لم يربطه دور بهذه المدرسة.

    super_admin يُرجع None لأنه لا يخضع لنطاق مدرسة واحد.
    """

    if current_user.is_authenticated and current_user.role == UserRole.super_admin:
        return None

    return getattr(current_user, "school_id", None) or None


def accessible_school_ids_for_user() -> set[int]:
    """أي المدارس التي يملك المستخدم الحالي صلة نشطة بها.

    يُستخدم هذا للأدوار التي لا تملك school_id مباشرة لكن لها
    صلاحية الوصول عبر اشتراكات الصفوف أو روابط الأدوار.
    """

    if not current_user.is_authenticated:
        return set()

    if current_user.role == UserRole.super_admin:
        return set()

    ids: set[int] = set()

    school_id = getattr(current_user, "school_id", None)
    if school_id:
        ids.add(int(school_id))

    for link in current_user.role_links:
        if link.is_active:
            ids.add(int(link.school_id))

    return ids


def assert_school_access(school_id: int) -> None:
    """تأكد أن المستخدم يصل إلى المدرسة المطلوبة، أو أطرح 403.

    الاستخدام الأمثل في المسارات التي تستقبل school_id صريحاً.
    """

    if current_user.is_authenticated and current_user.role == UserRole.super_admin:
        return

    if current_school_id() != school_id:
        abort(403)


def assert_user_belongs_to_accessible_school(user: User) -> None:
    """تأكد أن المستخدم المطلوب يرتبط إحدى مدارس接入 الخاصة بالمستخدم الحالي.

    مفيد في مسارات مثل `/api/v1/users/<id>` حيث ي Indirectly يستنتج
    النطاق عبر التقاطعات بين الروابط النشطة.
    """

    if current_user.is_authenticated and current_user.role == UserRole.super_admin:
        return

    current_ids = accessible_school_ids_for_user()
    if not current_ids:
        abort(403)

    user_ids = {
        int(link.school_id)
        for link in user.role_links
        if link.is_active and getattr(link, "school_id", None) is not None
    }

    if not (current_ids & user_ids):
        abort(403)


def schools_query_for_current_user() -> Any:
    """استعلام المدارس المخصّص داخلياً للمستخدم الحالي."""

    query = School.query.filter(School.is_active.is_(True))

    if current_user.is_authenticated and current_user.role == UserRole.super_admin:
        return query

    school_id = current_user_school_id()
    if school_id:
        query = query.filter(School.id == school_id)
    else:
        query = query.filter(False)

    return query


def classes_query_for_current_user() -> Any:
    """استعلام الصفوف المخصّص داخلياً للمستخدم الحالي."""

    query = ClassRoom.query.filter(ClassRoom.is_active.is_(True))

    if current_user.is_authenticated and current_user.role == UserRole.super_admin:
        return query

    school_id = current_user_school_id()
    if school_id:
        query = query.filter(ClassRoom.school_id == school_id)
    else:
        member_ids = (
            ClassMember.query.filter(ClassMember.user_id == current_user.id, ClassMember.status == "active")
            .with_entities(ClassMember.class_id)
            .scalar_subquery()
        )
        query = query.filter(ClassRoom.id.in_(member_ids))

    return query


def users_query_for_current_user() -> Any:
    """استعلام المستخدمين المخصّص داخلياً للمستخدم الحالي."""

    query = User.query.filter(User.is_active.is_(True))

    if current_user.is_authenticated and current_user.role == UserRole.super_admin:
        return query

    school_id = current_user_school_id()
    if school_id:
        user_ids_in_school = (
            UserRoleLink.query.filter(UserRoleLink.school_id == school_id, UserRoleLink.is_active.is_(True))
            .with_entities(UserRoleLink.user_id)
            .scalar_subquery()
        )
        query = query.filter(User.id.in_(user_ids_in_school))
    else:
        member_class_ids = (
            ClassMember.query.filter(ClassMember.user_id == current_user.id, ClassMember.status == "active")
            .with_entities(ClassMember.class_id)
            .scalar_subquery()
        )
        member_user_ids = (
            ClassMember.query.filter(ClassMember.class_id.in_(member_class_ids), ClassMember.status == "active")
            .with_entities(ClassMember.user_id)
            .scalar_subquery()
        )
        query = query.filter(User.id.in_(member_user_ids))

    return query


def lesson_access_query_for_current_user() -> Any:
    """استعلام الدروس المرتبطة بالصفوف التي يصل إليها المستخدم الحالي."""

    query = Lesson.query

    if current_user.is_authenticated and current_user.role == UserRole.super_admin:
        return query

    if current_user.is_authenticated and current_user.role in (
        UserRole.school_admin,
        UserRole.teacher,
    ):
        school_id = current_user_school_id()
        if school_id:
            class_ids_query = (
                ClassMember.query.filter(ClassMember.user_id == current_user.id, ClassMember.status == "active")
                .with_entities(ClassMember.class_id)
                .scalar_subquery()
            )
            query = query.filter(Lesson.class_id.in_(class_ids_query))
        else:
            query = query.filter(False)
    else:
        class_ids_query = (
            ClassMember.query.filter(ClassMember.user_id == current_user.id, ClassMember.status == "active")
            .with_entities(ClassMember.class_id)
            .scalar_subquery()
        )
        query = query.filter(Lesson.class_id.in_(class_ids_query))

    return query
