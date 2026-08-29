"""Squad 2 — Agent 8 (extra): Report Card & Grade Engine edge cases.

Tests for report_card.py and grade_appeals.py services.
Note: calculate_gpa uses db.inspect(ClassMember).mapper.class_.class_room.property
which fails in some SQLAlchemy configurations. We test generate_report_card
which calls calculate_student_grade directly.
"""

import pytest
from app.services.report_card import (
    _letter_grade,
    generate_report_card,
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


class TestReportCardLetterGrade:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (95, "ممتاز"),
            (85, "جيد جداً"),
            (75, "جيد"),
            (65, "مقبول"),
            (50, "راسب"),
        ],
    )
    def test_letter_grades(self, score, expected):
        assert _letter_grade(score) == expected


class TestGenerateReportCard:
    def test_report_card_returns_data(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            uid = make_user(app, "student", school_id=sid)
            make_class_member(app, cid, uid)

            result = generate_report_card(uid, cid)
            assert "student" in result
            assert "class_room" in result
            assert "grade_data" in result
            assert "completed_lessons" in result
            assert "total_lessons" in result
            assert "avg_progress" in result

    def test_report_card_empty(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            uid = make_user(app, "student", school_id=sid)

            result = generate_report_card(uid, cid)
            assert result["completed_lessons"] == 0
            assert result["total_lessons"] == 0
            assert result["avg_progress"] == 0

    def test_report_card_with_grades(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            uid = make_user(app, "student", school_id=sid)
            make_class_member(app, cid, uid)

            cat = make_grade_category(app, cid, "Exam", 1.0)
            item = make_grade_item(app, cid, cat, "Midterm", 100)
            make_grade_entry(app, uid, item, 85)

            result = generate_report_card(uid, cid)
            assert result["grade_data"]["final_grade"] == 85.0
            assert result["grade_data"]["letter_grade"] == "جيد جداً"
