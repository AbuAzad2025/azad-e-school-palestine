"""اختبارات C2 — محرك حساب الدرجات (calculate_student_grade, letter grades)."""

from app.extensions import db
from tests.conftest import (
    make_class, make_class_member, make_grade, make_grade_category,
    make_grade_entry, make_grade_item, make_school, make_subject, make_user,
)


def test_perfect_score_muntaz(app):
    """درجة 100% = ممتاز."""
    from app.services.grade_calc import calculate_student_grade

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)
    make_class_member(app, class_id, student_id)
    with app.app_context():
        cat_id = make_grade_category(app, class_id, "الفصل", 1.0)
        item_id = make_grade_item(app, class_id, cat_id, "اختبار نهائي", 100)
        make_grade_entry(app, student_id, item_id, 95)
        result = calculate_student_grade(student_id, class_id)
        assert result["final_grade"] == 95.0
        assert result["letter_grade"] == "ممتاز"


def test_score_65_maqbool(app):
    """درجة 65% = مقبول."""
    from app.services.grade_calc import calculate_student_grade

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)
    make_class_member(app, class_id, student_id)
    with app.app_context():
        cat_id = make_grade_category(app, class_id, "ال.semester", 1.0)
        item_id = make_grade_item(app, class_id, cat_id, "اختبار", 100)
        make_grade_entry(app, student_id, item_id, 65)
        result = calculate_student_grade(student_id, class_id)
        assert result["letter_grade"] == "مقبول"


def test_score_40_rasib(app):
    """درجة 40% = راسب."""
    from app.services.grade_calc import calculate_student_grade

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)
    make_class_member(app, class_id, student_id)
    with app.app_context():
        cat_id = make_grade_category(app, class_id, "نهائي", 1.0)
        item_id = make_grade_item(app, class_id, cat_id, "اختبار", 100)
        make_grade_entry(app, student_id, item_id, 40)
        result = calculate_student_grade(student_id, class_id)
        assert result["letter_grade"] == "راسب"


def test_weighted_average_two_categories(app):
    """متوسط مرجّح من قسمين بأوزان مختلفة."""
    from app.services.grade_calc import calculate_student_grade

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)
    make_class_member(app, class_id, student_id)
    with app.app_context():
        cat1 = make_grade_category(app, class_id, "أول", 0.4)
        cat2 = make_grade_category(app, class_id, "ثاني", 0.6)
        item1 = make_grade_item(app, class_id, cat1, "اختبار1", 20)
        item2 = make_grade_item(app, class_id, cat2, "اختبار2", 20)
        make_grade_entry(app, student_id, item1, 18)   # 90%
        make_grade_entry(app, student_id, item2, 12)   # 60%
        # weighted = 90*0.4 + 60*0.6 = 36+36 = 72
        result = calculate_student_grade(student_id, class_id)
        assert result["final_grade"] == 72.0


def test_no_grades_returns_zero(app):
    """طالب بدون درجات = صفر."""
    from app.services.grade_calc import calculate_student_grade

    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)
    make_class_member(app, class_id, student_id)
    with app.app_context():
        result = calculate_student_grade(student_id, class_id)
        assert result["final_grade"] == 0
        assert result["letter_grade"] == "راسب"
