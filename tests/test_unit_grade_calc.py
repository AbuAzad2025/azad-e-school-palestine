"""Unit tests for app.services.grade_calc and app.services.gradebook."""

from app.services.grade_calc import (
    ARABIC_GRADES,
    _letter_grade,
    calculate_student_grade,
    class_grades_summary,
)
from app.services.gradebook import (
    attendance_days,
    attendance_summary,
    create_assignment,
    create_category,
    get_attendance,
    list_assignments,
    list_categories,
    record_attendance,
)
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_school,
    make_subject,
    make_user,
)


class TestLetterGrade:
    def test_excellent(self):
        assert _letter_grade(95) == "ممتاز"

    def test_very_good(self):
        assert _letter_grade(85) == "جيد جداً"

    def test_good(self):
        assert _letter_grade(75) == "جيد"

    def test_acceptable(self):
        assert _letter_grade(65) == "مقبول"

    def test_failing(self):
        assert _letter_grade(50) == "راسب"

    def test_boundary_90(self):
        assert _letter_grade(90) == "ممتاز"

    def test_boundary_80(self):
        assert _letter_grade(80) == "جيد جداً"

    def test_boundary_0(self):
        assert _letter_grade(0) == "راسب"

    def test_arabic_grades_ordering(self):
        # Thresholds should be in descending order
        thresholds = [t for t, _ in ARABIC_GRADES]
        assert thresholds == sorted(thresholds, reverse=True)


class TestCalculateStudentGrade:
    def test_empty_class_returns_zeros(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            sid_student = make_user(app, "student", school_id=sid)

            result = calculate_student_grade(sid_student, cid)
            assert result["final_grade"] == 0
            assert result["letter_grade"] == "راسب"
            assert result["categories"] == []

    def test_with_category_and_item(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student_id = make_user(app, "student", school_id=sid)

            cat_id = make_grade_category(app, cid, "الفصل الأول", 1.0)
            item_id = make_grade_item(app, cid, cat_id, "امتحان", 100)
            make_grade_entry(app, student_id, item_id, 85)

            result = calculate_student_grade(student_id, cid)
            assert result["final_grade"] == 85.0
            assert result["letter_grade"] == "جيد جداً"
            assert len(result["categories"]) == 1

    def test_weighted_average(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student_id = make_user(app, "student", school_id=sid)

            cat1 = make_grade_category(app, cid, " midterm", 0.4)
            item1 = make_grade_item(app, cid, cat1, "Midterm", 100)
            make_grade_entry(app, student_id, item1, 80)

            cat2 = make_grade_category(app, cid, "Final", 0.6)
            item2 = make_grade_item(app, cid, cat2, "Final", 100)
            make_grade_entry(app, student_id, item2, 90)

            result = calculate_student_grade(student_id, cid)
            expected = round(80 * 0.4 + 90 * 0.6, 2)
            assert result["total_weighted_score"] == expected

    def test_partial_entries(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student_id = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "Cat", 1.0)
            item1 = make_grade_item(app, cid, cat, "Q1", 50)
            make_grade_item(app, cid, cat, "Q2", 50)
            make_grade_entry(app, student_id, item1, 40)
            # No entry for item2

            result = calculate_student_grade(student_id, cid)
            # Only item1 graded: 40/50 = 80%
            assert result["final_grade"] == 80.0


class TestClassGradesSummary:
    def test_empty_class(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)

            results = class_grades_summary(cid)
            assert results == []

    def test_sorted_by_grade(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)

            s1 = make_user(app, "student", school_id=sid)
            s2 = make_user(app, "student", school_id=sid)
            make_class_member(app, cid, s1)
            make_class_member(app, cid, s2)

            cat = make_grade_category(app, cid, "Grade", 1.0)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, s1, item, 90)
            make_grade_entry(app, s2, item, 70)

            results = class_grades_summary(cid)
            assert len(results) == 2
            assert results[0]["final_grade"] >= results[1]["final_grade"]


class TestAssignmentService:
    def test_create_assignment(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)

            assignment, error = create_assignment(cid, "واجب 1", "محتوى")
            assert error is None
            assert assignment is not None
            assert assignment.title == "واجب 1"

    def test_create_assignment_empty_title(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)

            assignment, error = create_assignment(cid, "", None)
            assert assignment is None
            assert "عنوان" in error

    def test_list_assignments(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)

            create_assignment(cid, "واجب 1")
            create_assignment(cid, "واجب 2")
            assignments = list_assignments(cid)
            assert len(assignments) == 2


class TestCategoryService:
    def test_create_category(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)

            cat = create_category(cid, "الفصل الأول", 0.5)
            assert cat.id is not None
            assert cat.name == "الفصل الأول"

    def test_list_categories(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)

            create_category(cid, "Cat 1")
            create_category(cid, "Cat 2")
            cats = list_categories(cid)
            assert len(cats) == 2


class TestAttendance:
    def test_record_and_get_attendance(self, app):
        from datetime import date

        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student_id = make_user(app, "student", school_id=sid)

            today = date.today()
            record_attendance(cid, today, {student_id: "present"})
            attendance = get_attendance(cid, today)
            assert student_id in attendance
            assert attendance[student_id].status == "present"

    def test_record_updates_existing(self, app):
        from datetime import date

        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student_id = make_user(app, "student", school_id=sid)

            today = date.today()
            record_attendance(cid, today, {student_id: "present"})
            record_attendance(cid, today, {student_id: "absent"})
            attendance = get_attendance(cid, today)
            assert attendance[student_id].status == "absent"

    def test_attendance_days(self, app):
        from datetime import date

        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student_id = make_user(app, "student", school_id=sid)

            today = date.today()
            record_attendance(cid, today, {student_id: "present"})
            days = attendance_days(cid)
            assert today in days

    def test_attendance_summary(self, app):
        from datetime import date

        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student_id = make_user(app, "student", school_id=sid)

            today = date.today()
            record_attendance(cid, today, {student_id: "present"})
            summary = attendance_summary(cid, student_id)
            assert len(summary) == 1
