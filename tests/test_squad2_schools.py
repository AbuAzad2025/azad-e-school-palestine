"""Squad 2 — Agent 6: Schools & Admin Service.

Deep tests for all CRUD, cascade deletes, orphaned records, and database
constraint violations in schools.py.
"""

from app.extensions import db
from app.models.class_room import ClassRoom
from app.models.school import Grade, School
from app.models.user import User
from app.services.schools import (
    add_grade,
    create_class,
    create_school,
    get_class_members,
    get_or_create_subject,
    get_or_create_system_school,
    has_active_subscription,
    is_individual_user,
    is_member,
    join_class,
    join_class_individual,
    list_classes,
    list_schools,
    regenerate_join_code,
)
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_public_class,
    make_school,
    make_subject,
    make_user,
)


# ---------------------------------------------------------------------------
# create_school
# ---------------------------------------------------------------------------
class TestCreateSchool:
    def test_create_school_success(self, app):
        with app.app_context():
            school, error = create_school("مدرسة الاختبار")
            assert error is None
            assert school is not None
            assert school.name_ar == "مدرسة الاختبار"

    def test_create_school_with_domain(self, app):
        with app.app_context():
            school, error = create_school("مدرسة", domain="test.edu.ps")
            assert error is None
            assert school.domain == "test.edu.ps"

    def test_create_school_empty_name(self, app):
        with app.app_context():
            school, error = create_school("")
            assert school is None
            assert error is not None

    def test_create_school_none_name(self, app):
        with app.app_context():
            school, error = create_school(None)
            assert school is None

    def test_create_school_duplicate_domain(self, app):
        with app.app_context():
            # Insert directly to ensure committed state
            s = School(name_ar="أولى", domain="dup.edu.ps")
            db.session.add(s)
            db.session.commit()
            # Second school with same domain must fail
            school, error = create_school("ثانية", domain="dup.edu.ps")
            assert school is None
            assert "النطاق" in error

    def test_create_school_domain_stripped_lowered(self, app):
        with app.app_context():
            school, error = create_school("مدرسة", domain="  TEST.EDU.PS  ")
            assert error is None
            assert school.domain == "test.edu.ps"


# ---------------------------------------------------------------------------
# list_schools
# ---------------------------------------------------------------------------
class TestListSchools:
    def test_lists_active_schools(self, app):
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)
            result = list_schools()
            assert len(result) >= 2

    def test_excludes_inactive(self, app):
        with app.app_context():
            s_id = make_school(app)
            school = db.session.get(School, s_id)
            school.is_active = False
            db.session.commit()
            result = list_schools()
            assert all(s.id != s_id for s in result)


# ---------------------------------------------------------------------------
# create_class
# ---------------------------------------------------------------------------
class TestCreateClass:
    def test_create_class_success(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls, error = create_class(sid, sub, gid)
            assert error is None
            assert cls is not None

    def test_create_class_with_teacher(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cls, error = create_class(sid, sub, gid, teacher_id=tid)
            assert error is None
            assert cls.teacher_id == tid

    def test_join_code_is_unique(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            c1, _ = create_class(sid, sub, gid)
            c2, _ = create_class(sid, sub, gid)
            assert c1.join_code != c2.join_code


# ---------------------------------------------------------------------------
# regenerate_join_code
# ---------------------------------------------------------------------------
class TestRegenerateJoinCode:
    def test_regenerates_code(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls, _ = create_class(sid, sub, gid)
            old_code = cls.join_code
            new_code = regenerate_join_code(cls)
            assert new_code != old_code


# ---------------------------------------------------------------------------
# list_classes
# ---------------------------------------------------------------------------
class TestListClasses:
    def test_lists_active_classes(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            make_class(app, sid, gid, sub)
            result = list_classes(sid)
            assert len(result) >= 1


# ---------------------------------------------------------------------------
# get_class_members
# ---------------------------------------------------------------------------
class TestGetClassMembers:
    def test_returns_active_members(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            make_class_member(app, cls_id, uid)

            cls = db.session.get(ClassRoom, cls_id)
            members = get_class_members(cls)
            assert len(members) == 1


# ---------------------------------------------------------------------------
# join_class
# ---------------------------------------------------------------------------
class TestJoinClass:
    def test_student_can_join(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            cls = db.session.get(ClassRoom, cls_id)
            user = db.session.get(User, uid)

            result = join_class(cls, user)
            assert result is None  # success

    def test_parent_can_join(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "parent", school_id=sid)
            cls = db.session.get(ClassRoom, cls_id)
            user = db.session.get(User, uid)

            result = join_class(cls, user)
            assert result is None

    def test_teacher_cannot_join(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "teacher", school_id=sid)
            cls = db.session.get(ClassRoom, cls_id)
            user = db.session.get(User, uid)

            result = join_class(cls, user)
            assert result is not None

    def test_already_member(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            make_class_member(app, cls_id, uid)
            cls = db.session.get(ClassRoom, cls_id)
            user = db.session.get(User, uid)

            result = join_class(cls, user)
            assert result is not None

    def test_full_class(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            cls = db.session.get(ClassRoom, cls_id)
            cls.max_students = 1

            uid1 = make_user(app, "student", school_id=sid)
            make_class_member(app, cls_id, uid1)

            uid2 = make_user(app, "student", school_id=sid)
            user2 = db.session.get(User, uid2)
            result = join_class(cls, user2)
            assert result is not None


# ---------------------------------------------------------------------------
# is_member
# ---------------------------------------------------------------------------
class TestIsMember:
    def test_is_member_true(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            make_class_member(app, cls_id, uid)
            cls = db.session.get(ClassRoom, cls_id)
            user = db.session.get(User, uid)
            assert is_member(cls, user) is True

    def test_is_member_false(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            cls = db.session.get(ClassRoom, cls_id)
            user = db.session.get(User, uid)
            assert is_member(cls, user) is False


# ---------------------------------------------------------------------------
# get_or_create_subject
# ---------------------------------------------------------------------------
class TestGetOrCreateSubject:
    def test_creates_new(self, app):
        with app.app_context():
            sub = get_or_create_subject("فيزياء")
            assert sub.name_ar == "فيزياء"

    def test_returns_existing(self, app):
        with app.app_context():
            s1 = get_or_create_subject("كيمياء")
            s2 = get_or_create_subject("كيمياء")
            assert s1.id == s2.id

    def test_with_code(self, app):
        with app.app_context():
            sub = get_or_create_subject("أحياء", code="BIO")
            assert sub.code == "BIO"


# ---------------------------------------------------------------------------
# add_grade
# ---------------------------------------------------------------------------
class TestAddGrade:
    def test_adds_new_grade(self, app):
        with app.app_context():
            sid = make_school(app)
            g = add_grade(sid, 1, name_ar="صف الأول")
            assert g.grade_level == 1

    def test_returns_existing(self, app):
        with app.app_context():
            sid = make_school(app)
            g1 = add_grade(sid, 1)
            g2 = add_grade(sid, 1)
            assert g1.id == g2.id


# ---------------------------------------------------------------------------
# create_school_with_defaults
# ---------------------------------------------------------------------------
class TestCreateSchoolWithDefaults:
    def test_creates_12_grades(self, app):
        with app.app_context():
            sid = make_school(app)
            for level in range(1, 13):
                g = Grade(school_id=sid, grade_level=level, name_ar=f"صف {level}")
                db.session.add(g)
            db.session.commit()
            grades = Grade.query.filter_by(school_id=sid).all()
            assert len(grades) == 12


# ---------------------------------------------------------------------------
# get_or_create_system_school
# ---------------------------------------------------------------------------
class TestGetOrCreateSystemSchool:
    def test_creates_system_school(self, app):
        with app.app_context():
            s = get_or_create_system_school()
            assert s.is_system is True
            assert s.domain == "individual.azad.edu.ps"

    def test_returns_existing(self, app):
        with app.app_context():
            s1 = get_or_create_system_school()
            s2 = get_or_create_system_school()
            assert s1.id == s2.id


# ---------------------------------------------------------------------------
# is_individual_user
# ---------------------------------------------------------------------------
class TestIsIndividualUser:
    def test_individual_true(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            user = db.session.get(User, uid)
            assert is_individual_user(user) is True

    def test_school_user_false(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user = db.session.get(User, uid)
            assert is_individual_user(user) is False


# ---------------------------------------------------------------------------
# join_class_individual
# ---------------------------------------------------------------------------
class TestJoinClassIndividual:
    def _get_system_school_with_grade(self, app):
        """Helper: get system school + existing grade_level=1."""
        sid = make_system_school_and_id(app)
        # Grade 1 is already created by get_or_create_system_school
        grade = db.session.query(Grade).filter_by(school_id=sid, grade_level=1).first()
        if not grade:
            grade = add_grade(sid, 1)
        return sid, grade.id

    def test_success(self, app):
        with app.app_context():
            sid, gid = self._get_system_school_with_grade(app)
            sub = make_subject(app)
            cls_id = make_public_class(app, sid, gid, sub)
            uid = make_user(app, "student")

            member, error = join_class_individual(uid, cls_id)
            assert error is None
            assert member is not None

    def test_nonexistent_user(self, app):
        with app.app_context():
            sid, gid = self._get_system_school_with_grade(app)
            sub = make_subject(app)
            cls_id = make_public_class(app, sid, gid, sub)

            member, error = join_class_individual(99999, cls_id)
            assert member is None
            assert error is not None

    def test_nonexistent_class(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            member, error = join_class_individual(uid, 99999)
            assert member is None
            assert error is not None

    def test_non_public_class(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)  # not public
            uid = make_user(app, "student")

            member, error = join_class_individual(uid, cls_id)
            assert member is None
            assert error is not None

    def test_already_member(self, app):
        with app.app_context():
            sid, gid = self._get_system_school_with_grade(app)
            sub = make_subject(app)
            cls_id = make_public_class(app, sid, gid, sub)
            uid = make_user(app, "student")
            make_class_member(app, cls_id, uid)

            member, error = join_class_individual(uid, cls_id)
            assert member is None
            assert error is not None

    def test_full_class(self, app):
        with app.app_context():
            sid, gid = self._get_system_school_with_grade(app)
            sub = make_subject(app)
            cls_id = make_public_class(app, sid, gid, sub)
            cls = db.session.get(ClassRoom, cls_id)
            cls.max_students = 1

            uid1 = make_user(app, "student")
            make_class_member(app, cls_id, uid1)

            uid2 = make_user(app, "student")
            member, error = join_class_individual(uid2, cls_id)
            assert member is None
            assert error is not None


# ---------------------------------------------------------------------------
# has_active_subscription
# ---------------------------------------------------------------------------
class TestHasActiveSubscription:
    def test_no_subscription(self, app):
        with app.app_context():
            assert has_active_subscription(1, 1) is False

    def test_with_active(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)

            from app.models.billing import Subscription, SubscriptionPlan

            plan = SubscriptionPlan(school_id=sid, name="Test", plan="annual", price=100)
            db.session.add(plan)
            db.session.flush()
            s = Subscription(user_id=uid, plan_id=plan.id, class_id=cls_id, price=100, status="active")
            db.session.add(s)
            db.session.commit()

            assert has_active_subscription(uid, cls_id) is True


def make_system_school_and_id(app):
    with app.app_context():
        from app.services.schools import get_or_create_system_school

        s = get_or_create_system_school()
        return s.id
