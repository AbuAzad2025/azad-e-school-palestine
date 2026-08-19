"""اختبارات سعة الصفوف الدراسية."""

from app.extensions import db
from app.models.class_room import ClassMember, ClassRoom
from app.services.schools import join_class


def test_class_without_capacity_allows_join(app):
    from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    student_id = make_user(app, role="student")
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        from app.models.user import User
        student = User.query.get(student_id)
        room = ClassRoom.query.get(class_id)
        result = join_class(room, student)
        assert result is None


def test_class_at_capacity_blocks_join(app):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        c = ClassRoom.query.get(class_id)
        c.max_students = 2
        db.session.commit()

        s1 = make_user(app, role="student")
        s2 = make_user(app, role="student")
        db.session.add(ClassMember(class_id=class_id, user_id=s1, status="active"))
        db.session.add(ClassMember(class_id=class_id, user_id=s2, status="active"))
        db.session.commit()

        s3_id = make_user(app, role="student")
        from app.models.user import User

        s3 = User.query.get(s3_id)
        room = ClassRoom.query.get(class_id)
        result = join_class(room, s3)
        assert result is not None


def test_class_below_capacity_allows_join(app):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        c = ClassRoom.query.get(class_id)
        c.max_students = 5
        db.session.commit()

        s1 = make_user(app, role="student")
        db.session.add(ClassMember(class_id=class_id, user_id=s1, status="active"))
        db.session.commit()

        s2_id = make_user(app, role="student")
        from app.models.user import User

        s2 = User.query.get(s2_id)
        room = ClassRoom.query.get(class_id)
        result = join_class(room, s2)
        assert result is None


def test_class_exact_capacity_blocks(app):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        c = ClassRoom.query.get(class_id)
        c.max_students = 1
        db.session.commit()

        s1 = make_user(app, role="student")
        db.session.add(ClassMember(class_id=class_id, user_id=s1, status="active"))
        db.session.commit()

        s2_id = make_user(app, role="student")
        from app.models.user import User

        s2 = User.query.get(s2_id)
        room = ClassRoom.query.get(class_id)
        result = join_class(room, s2)
        assert result is not None


def test_member_removed_frees_spot(app):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        c = ClassRoom.query.get(class_id)
        c.max_students = 2
        db.session.commit()

        s1 = make_user(app, role="student")
        s2 = make_user(app, role="student")
        db.session.add(ClassMember(class_id=class_id, user_id=s1, status="active"))
        db.session.add(ClassMember(class_id=class_id, user_id=s2, status="active"))
        db.session.commit()

        m = ClassMember.query.filter_by(class_id=class_id, user_id=s1).first()
        m.status = "removed"
        db.session.commit()

        s3_id = make_user(app, role="student")
        from app.models.user import User

        s3 = User.query.get(s3_id)
        room = ClassRoom.query.get(class_id)
        result = join_class(room, s3)
        assert result is None


def test_max_students_zero_allows_unlimited(app):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        c = ClassRoom.query.get(class_id)
        c.max_students = 0
        db.session.commit()

        for _ in range(5):
            sid = make_user(app, role="student")
            db.session.add(ClassMember(class_id=class_id, user_id=sid, status="active"))
        db.session.commit()

        s_new_id = make_user(app, role="student")
        from app.models.user import User

        s_new = User.query.get(s_new_id)
        room = ClassRoom.query.get(class_id)
        result = join_class(room, s_new)
        assert result is None


def test_class_with_capacity_set(app):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        c = ClassRoom.query.get(class_id)
        c.max_students = 30
        db.session.commit()
        c2 = ClassRoom.query.get(class_id)
        assert c2.max_students == 30


def test_existing_member_not_affected_by_capacity(app):
    from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_user

    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher")
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)

    with app.app_context():
        c = ClassRoom.query.get(class_id)
        c.max_students = 1
        db.session.commit()

        s1 = make_user(app, role="student")
        db.session.add(ClassMember(class_id=class_id, user_id=s1, status="active"))
        db.session.commit()

        from app.models.user import User

        s1_user = User.query.get(s1)
        room = ClassRoom.query.get(class_id)
        result = join_class(room, s1_user)
        assert result is not None
