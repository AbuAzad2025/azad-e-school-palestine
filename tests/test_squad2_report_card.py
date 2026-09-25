"""Squad 2 — Agent 8 (extra): Report Card & Grade Engine edge cases.

Tests for report_card.py and grade_appeals.py services.
Note: calculate_gpa uses db.inspect(ClassMember).mapper.class_.class_room.property
which fails in some SQLAlchemy configurations. We test generate_report_card
which calls calculate_student_grade directly.

PDF generation (build_report_card_story / render_report_card_pdf) goes through
the shared reportlab infrastructure in app/core/pdf.py — real %PDF bytes.
"""

import pytest
from app.services.report_card import (
    _letter_grade,
    build_report_card_story,
    generate_report_card,
    render_report_card_pdf,
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


class TestReportCardPdf:
    def test_render_pdf_returns_real_bytes(self, app, tmp_path, monkeypatch):
        """PDF حقيقي: ترويسة %PDF + حجم معقول + ملف مكتوب على القرص."""
        monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
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

            pdf = render_report_card_pdf(uid, cid)

        assert isinstance(pdf, bytes)
        assert bytes(pdf)[:5] == b"%PDF-"
        assert len(pdf) > 1000
        report_dir = tmp_path / "generated" / "report_cards" / "0"
        assert report_dir.is_dir() and any(report_dir.iterdir())

    def test_render_pdf_missing_student_returns_none(self, app):
        with app.app_context():
            assert render_report_card_pdf(999999, 888888) is None

    def test_build_story_fills_elements(self, app):
        """قصة بطاقة الدرجات تمتلئ بجداول platypus (تستخدمها الخدمة والمهمة)."""
        from app.core.pdf import blank_pdf_document
        from reportlab.platypus import Table

        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            uid = make_user(app, "student", school_id=sid)
            make_class_member(app, cid, uid)

            data = generate_report_card(uid, cid)
            doc, story = blank_pdf_document()
            build_report_card_story(
                story,
                uid,
                cid,
                data["grade_data"],
                student=data["student"],
                class_room=data["class_room"],
                progress={
                    "completed_lessons": data["completed_lessons"],
                    "total_lessons": data["total_lessons"],
                    "avg_progress": data["avg_progress"],
                },
            )

        assert len(story) >= 8  # عنوان + وصف + meta + معلومات + أقسام + ملخص
        assert any(isinstance(el, Table) for el in story)

    def test_build_story_no_grades_branch(self, app):
        """طالب بلا درجات → رسالة بديلة بدل جدول الأقسام."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cid = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            make_class_member(app, cid, uid)

            from app.core.pdf import blank_pdf_document
            from reportlab.platypus import Table

            data = generate_report_card(uid, cid)
            doc, story = blank_pdf_document()
            build_report_card_story(story, uid, cid, data["grade_data"])

        assert not data["grade_data"].get("categories")
        # جدولان فقط: معلومات الطالب + الملخص — بلا جدول أقسام
        tables = [el for el in story if isinstance(el, Table)]
        assert len(tables) == 2
