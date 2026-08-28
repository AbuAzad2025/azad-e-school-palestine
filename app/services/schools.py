"""خدمات المدارس والصفوف — منطق موحّد (تينانتس: School هي الجذر بلا school_id)."""

import secrets

from sqlalchemy.orm import joinedload

from app.core.db import tx
from app.core.i18n import _
from app.extensions import db
from app.models.class_room import ClassMember, ClassRoom
from app.models.school import Grade, School, Subject
from app.models.user import User, UserRole


def create_school(
    name_ar: str, domain: str | None = None, name_en: str | None = None
) -> tuple[School | None, str | None]:
    """ينشئ مدرسة. يعيد (school, error)."""
    name_ar = (name_ar or "").strip()
    if not name_ar:
        return None, _("اسم المدرسة مطلوب.")
    if domain:
        domain = domain.strip().lower()
        if School.query.filter_by(domain=domain).first():
            return None, _("هذا النطاق مستخدم لمدرسة أخرى.")

    def _create():
        s = School(name_ar=name_ar, name_en=name_en, domain=domain or None)
        db.session.add(s)
        return s

    return tx(_create), None


def list_schools():
    return School.query.filter_by(is_active=True).order_by(School.name_ar).all()


def _join_code() -> str:
    return secrets.token_urlsafe(6)


def create_class(
    school_id: int,
    subject_id: int,
    grade_id: int,
    teacher_id: int | None = None,
    semester: str | None = None,
    name: str | None = None,
    price_first_term=None,
    price_second_term=None,
    price_annual=None,
    currency: str = "ILS",
) -> tuple[ClassRoom | None, str | None]:
    """ينشئ صفاً داخل مدرسة. يعيد (class, error)."""
    code = _join_code()
    while ClassRoom.query.filter_by(join_code=code).first():
        code = _join_code()

    def _create():
        cr = ClassRoom(
            school_id=school_id,
            subject_id=subject_id,
            grade_id=grade_id,
            teacher_id=teacher_id,
            semester=semester,
            name=name,
            join_code=code,
            price_first_term=price_first_term,
            price_second_term=price_second_term,
            price_annual=price_annual,
            currency=currency,
        )
        db.session.add(cr)
        return cr

    return tx(_create), None


def regenerate_join_code(class_room: ClassRoom) -> str:
    """كود جديد للصف (لإبطال الكود المسرّب)."""

    def _regenerate():
        code = _join_code()
        while ClassRoom.query.filter_by(join_code=code).first():
            code = _join_code()
        class_room.join_code = code
        return code

    return tx(_regenerate)


def list_classes(school_id: int):
    from app.core.tenancy import scope_by_school

    return (
        scope_by_school(ClassRoom, school_id)
        .filter_by(is_active=True)
        .options(joinedload(ClassRoom.subject), joinedload(ClassRoom.grade), joinedload(ClassRoom.teacher))
        .order_by(ClassRoom.id.desc())
        .all()
    )


def get_class_members(class_room: ClassRoom):
    return (
        ClassMember.query.filter_by(class_id=class_room.id, status="active")
        .options(joinedload(ClassMember.user))
        .order_by(ClassMember.joined_at)
        .all()
    )


def join_class(class_room: ClassRoom, user: User) -> str | None:
    """انضمام طالب/ولي أمر لصف برمز. يعيد رسالة خطأ أو None عند النجاح."""
    if user.role not in (UserRole.student, UserRole.parent):
        return "الحساب الحالي لا يمكنه الانضمام كطالب."
    existing = ClassMember.query.filter_by(class_id=class_room.id, user_id=user.id).first()
    if existing:
        return "أنت عضو في هذا الصف مسبقاً."
    if class_room.max_students:
        current_count = ClassMember.query.filter_by(class_id=class_room.id, status="active").count()
        if current_count >= class_room.max_students:
            return "الصف ممتلئ. لا يمكن الانضمام."

    def _join():
        db.session.add(ClassMember(class_id=class_room.id, user_id=user.id, status="active", joined_at=db.func.now()))

    tx(_join)
    return None


def is_member(class_room: ClassRoom, user: User) -> bool:
    return ClassMember.query.filter_by(class_id=class_room.id, user_id=user.id, status="active").first() is not None


def get_or_create_subject(name_ar: str, code: str | None = None) -> Subject:
    """جلب مادة أو إنشاؤها (مشاركة بين المدارس)."""
    name_ar = name_ar.strip()
    subject = Subject.query.filter_by(name_ar=name_ar).first()
    if subject:
        return subject

    def _create():
        s = Subject(name_ar=name_ar, code=code)
        db.session.add(s)
        return s

    return tx(_create)


def add_grade(school_id: int, grade_level: int, name_ar: str | None = None, stage: str | None = None) -> Grade:
    """مستوى دراسي (1..12) داخل المدرسة — غير مكرر."""
    existing = Grade.query.filter_by(school_id=school_id, grade_level=grade_level).first()
    if existing:
        return existing

    def _add():
        g = Grade(school_id=school_id, grade_level=grade_level, name_ar=name_ar, stage=stage)
        db.session.add(g)
        return g

    return tx(_add)


def create_school_with_defaults(name_ar: str, domain: str | None = None) -> tuple[School | None, str | None]:
    """مدرسة + مستوياتها 1..12 (تسريع الإعداد)."""
    school, error = create_school(name_ar, domain)
    if error or school is None:
        return school, error
    for level in range(1, 13):
        add_grade(school.id, level)
    return school, None


SYSTEM_SCHOOL_DOMAIN = "individual.azad.edu.ps"


def get_or_create_system_school() -> School:
    """获取或创建系统学校「أزاد للتعليم الفردي»."""
    school = School.query.filter_by(domain=SYSTEM_SCHOOL_DOMAIN).first()
    if school:
        return school

    def _create():
        s = School(
            name_ar="أزاد للتعليم الفردي",
            name_en="Azad Individual Learning",
            domain=SYSTEM_SCHOOL_DOMAIN,
            is_system=True,
        )
        db.session.add(s)
        db.session.flush()
        for level in range(1, 13):
            existing = Grade.query.filter_by(school_id=s.id, grade_level=level).first()
            if not existing:
                db.session.add(Grade(school_id=s.id, grade_level=level, name_ar=f"صف {level}"))
        return s

    return tx(_create)


def is_individual_user(user) -> bool:
    """True if user has no active role link to a non-system school."""
    return not user.belongs_to_school


def has_active_subscription(student_id: int, class_id: int) -> bool:
    """Check if student has an active subscription for a class."""
    from app.models.billing import Subscription

    return Subscription.query.filter_by(user_id=student_id, class_id=class_id, status="active").first() is not None


def join_class_individual(student_id: int, class_id: int) -> tuple[ClassMember | None, str | None]:
    """Individual student joins a public class. Returns (member_or_none, error_or_none)."""
    user = db.session.get(User, student_id)
    cls = db.session.get(ClassRoom, class_id)
    if not user or not cls:
        return None, _("المستخدم أو الصف غير موجود.")
    if not cls.is_public:
        return None, _("هذا الصف غير متاح للاشتراك الفردي.")
    if is_member(cls, user):
        return None, _("أنت عضو في هذا الصف مسبقاً.")
    if cls.max_students:
        current_count = ClassMember.query.filter_by(class_id=cls.id, status="active").count()
        if current_count >= cls.max_students:
            return None, _("الصف ممتلئ.")

    def _join():
        db.session.add(ClassMember(class_id=cls.id, user_id=user.id, status="active", joined_at=db.func.now()))

    tx(_join)
    member = ClassMember.query.filter_by(class_id=cls.id, user_id=user.id).first()
    return member, None
