"""اختبارات C14 — خدمات التصدير إلى Excel."""

from app.extensions import db
from tests.conftest import (
    make_class, make_class_member, make_grade, make_grade_category,
    make_grade_entry, make_grade_item, make_lesson, make_school,
    make_student_progress, make_subject, make_user,
)


def test_export_students_excel(app):
    """تصدير قائمة الطلاب إلى Excel."""
    from app.services.export import export_students_excel

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        make_class_member(app, class_id, student_id)
        result = export_students_excel(class_id)
        assert isinstance(result, bytes)
        assert len(result) > 0


def test_export_grades_excel(app):
    """تصدير درجات الصف إلى Excel."""
    from app.services.export import export_grades_excel

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        make_class_member(app, class_id, student_id)
        cat_id = make_grade_category(app, class_id, "اختبارات", 1.0)
        item_id = make_grade_item(app, class_id, cat_id, "امتحان", 20)
        make_grade_entry(app, student_id, item_id, 18)
        result = export_grades_excel(class_id)
        assert isinstance(result, bytes)
        assert len(result) > 0


def test_export_progress_excel(app):
    """تصدير تقدم الطلاب إلى Excel."""
    from app.services.export import export_progress_excel

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        lesson_id = make_lesson(app, class_id)
        make_student_progress(app, student_id, lesson_id, class_id, pct=75, seconds=600)
        result = export_progress_excel(class_id)
        assert isinstance(result, bytes)
        assert len(result) > 0
