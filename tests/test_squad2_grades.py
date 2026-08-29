"""Squad 2 — Agent 8: Report Cards & Grade Calculations.

Tests division-by-zero, negative marks, weighted average boundaries,
missing grade categories, and rounding precision.
"""

import pytest
from app.services.grade_calc import (
    ARABIC_GRADES,
    _letter_grade,
    calculate_student_grade,
    class_grades_summary,
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


# ---------------------------------------------------------------------------
# _letter_grade — all boundaries
# ---------------------------------------------------------------------------
class TestLetterGrade:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (95, "ممتاز"),
            (90, "ممتاز"),
            (89, "جيد جداً"),
            (80, "جيد جداً"),
            (79, "جيد"),
            (70, "جيد"),
            (69, "مقبول"),
            (60, "مقبول"),
            (59, "راسب"),
            (0, "راسب"),
            (100, "ممتاز"),
            (45, "راسب"),
            (1, "راسب"),
        ],
    )
    def test_letter_grades(self, score, expected):
        assert _letter_grade(score) == expected

    def test_grades_descending(self):
        thresholds = [t for t, _ in ARABIC_GRADES]
        assert thresholds == sorted(thresholds, reverse=True)


# ---------------------------------------------------------------------------
# calculate_student_grade — edge cases
# ---------------------------------------------------------------------------
class TestCalculateStudentGrade:
    def test_empty_class(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            result = calculate_student_grade(student, cid)
            assert result["final_grade"] == 0
            assert result["letter_grade"] == "راسب"
            assert result["total_weight"] == 0

    def test_zero_weight_category(self, app):
        """Category with weight=0 should not contribute to final grade."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "Zero Weight", 0)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, student, item, 85)

            result = calculate_student_grade(student, cid)
            assert result["final_grade"] == 0  # weight is 0
            assert result["total_weight"] == 0

    def test_zero_max_mark_item(self, app):
        """Item with max_mark=0 should not crash (division by zero avoided)."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "Cat", 1.0)
            item = make_grade_item(app, cid, cat, "Zero Mark", 0)
            make_grade_entry(app, student, item, 10)

            result = calculate_student_grade(student, cid)
            # pct should be None (max_mark=0), category_pct should be 0
            assert result["final_grade"] == 0

    def test_no_entry_for_item(self, app):
        """Item with no grade entry should not contribute to the percentage."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "Cat", 1.0)
            item1 = make_grade_item(app, cid, cat, "Q1", 50)
            make_grade_item(app, cid, cat, "Q2", 50)
            make_grade_entry(app, student, item1, 50)
            # No entry for Q2

            result = calculate_student_grade(student, cid)
            # 50/50 = 100% for Q1, Q2 has no entry
            assert result["final_grade"] == 100.0

    def test_multiple_categories_weighted(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat1 = make_grade_category(app, cid, "Midterm", 0.4)
            item1 = make_grade_item(app, cid, cat1, "Midterm", 100)
            make_grade_entry(app, student, item1, 80)

            cat2 = make_grade_category(app, cid, "Final", 0.6)
            item2 = make_grade_item(app, cid, cat2, "Final", 100)
            make_grade_entry(app, student, item2, 90)

            result = calculate_student_grade(student, cid)
            expected_weighted = round(80 * 0.4 + 90 * 0.6, 2)
            assert result["total_weighted_score"] == expected_weighted

    def test_all_zero_marks(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "Cat", 1.0)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, student, item, 0)

            result = calculate_student_grade(student, cid)
            assert result["final_grade"] == 0
            assert result["letter_grade"] == "راسب"

    def test_perfect_score(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "All", 1.0)
            item = make_grade_item(app, cid, cat, "Perfect", 100)
            make_grade_entry(app, student, item, 100)

            result = calculate_student_grade(student, cid)
            assert result["final_grade"] == 100.0
            assert result["letter_grade"] == "ممتاز"

    def test_category_with_no_weight(self, app):
        """Category with None weight should treat weight as 0."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "NoWeight", None)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, student, item, 85)

            result = calculate_student_grade(student, cid)
            # Weight is None → treated as 0
            assert result["final_grade"] == 0

    def test_item_with_none_max_mark(self, app):
        """Item with None max_mark should not crash."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            cat = make_grade_category(app, cid, "Cat", 1.0)
            item = make_grade_item(app, cid, cat, "NoMax", None)
            make_grade_entry(app, student, item, 50)

            result = calculate_student_grade(student, cid)
            # max_mark=0 (None treated as 0), earned=50 → no pct
            assert result["final_grade"] == 0


# ---------------------------------------------------------------------------
# class_grades_summary
# ---------------------------------------------------------------------------
class TestClassGradesSummary:
    def test_empty_class(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            assert class_grades_summary(cid) == []

    def test_sorted_descending(self, app):
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
            make_grade_entry(app, s1, item, 95)
            make_grade_entry(app, s2, item, 60)

            results = class_grades_summary(cid)
            assert len(results) == 2
            assert results[0]["final_grade"] >= results[1]["final_grade"]

    def test_includes_student_object(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub_id, teacher_id=tid)
            s1 = make_user(app, "student", school_id=sid)
            make_class_member(app, cid, s1)

            results = class_grades_summary(cid)
            assert len(results) == 1
            assert results[0]["student_id"] == s1
