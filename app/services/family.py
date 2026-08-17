"""خدمات روابط الأسرة — ربط ولي الأمر بالطالب."""

import secrets

from app.core.db import tx
from app.extensions import db
from app.models.family import FamilyLink, FamilyLinkCode
from app.models.user import User, UserRole


def generate_link_code(student_id: int) -> tuple[str | None, str | None]:
    """ينشئ رمز ربط جديد للطالب (8 أحرف)."""
    student = db.session.get(User, student_id)
    if not student or student.role != UserRole.student:
        return None, "المستخدم ليس طالباً."

    code = secrets.token_urlsafe(6)[:8].upper()

    def _create():
        return FamilyLinkCode(student_id=student_id, code=code)

    result = tx(_create)
    return result.code if result else None, None


def link_parent(parent_id: int, code: str) -> tuple[FamilyLink | None, str | None]:
    """يربط ولي الأمر بالطالب عبر الرمز."""
    code = (code or "").strip().upper()
    if not code:
        return None, "الرمز مطلوب."

    parent = db.session.get(User, parent_id)
    if not parent or parent.role != UserRole.parent:
        return None, "المستخدم ليس ولي أمر."

    link_code = FamilyLinkCode.query.filter_by(code=code, used=False).first()
    if not link_code:
        return None, "الرمز غير صالح أو مستخدم مسبقاً."

    existing = FamilyLink.query.filter_by(parent_id=parent_id, student_id=link_code.student_id, status="active").first()
    if existing:
        return None, "أنت مرتبط بهذا الطالب مسبقاً."

    def _link():
        link_code.used = True
        link_code.used_by = parent_id
        return FamilyLink(
            parent_id=parent_id,
            student_id=link_code.student_id,
            status="active",
        )

    return tx(_link), None


def list_children(parent_id: int) -> list[FamilyLink]:
    """يُعيد قائمة الأبناء المرتبطين بولي الأمر."""
    return FamilyLink.query.filter_by(parent_id=parent_id, status="active").all()


def remove_link(link_id: int, parent_id: int) -> tuple[bool, str | None]:
    """يزيل رابط ولي أمر بالطالب."""
    link = db.session.get(FamilyLink, link_id)
    if not link or link.parent_id != parent_id:
        return False, "الرابط غير موجود."

    def _remove():
        link.status = "removed"

    tx(_remove)
    return True, None


def is_parent_of(parent_id: int, student_id: int) -> bool:
    """يتحقق مما إذا كان ولي الأمر مرتبطاً بالطالب."""
    return FamilyLink.query.filter_by(parent_id=parent_id, student_id=student_id, status="active").first() is not None


def get_parent(student_id: int) -> User | None:
    """يُعيد ولي الأمر الأول للطالب."""
    link = FamilyLink.query.filter_by(student_id=student_id, status="active").first()
    if link:
        return db.session.get(User, link.parent_id)
    return None
