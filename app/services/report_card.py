"""كشوف الدرجات — GPA + تقرير الطالب."""

from app.extensions import db
from app.models.class_room import ClassMember
from app.services.grade_calc import calculate_student_grade


def calculate_gpa(student_id: int, school_id: int) -> dict:
    """حساب المعدل التراكمي لطالب في مدرسة عبر جميع صفوفه."""
    memberships = (
        ClassMember.query.join(db.inspect(ClassMember).mapper.class_.class_room.property)
        .filter(
            ClassMember.user_id == student_id,
            ClassMember.status == "active",
        )
        .all()
    )
    # بسيط: نجمع درجات جميع الصفوف ونحسب المتوسط
    total_weighted = 0.0
    total_weight = 0.0
    class_grades = []
    for m in memberships:
        grade_data = calculate_student_grade(student_id, m.class_id)
        cat_data = grade_data["categories"]
        for cat in cat_data:
            total_weighted += cat["weighted_score"]
            total_weight += cat["weight"]
        class_grades.append(
            {
                "class_id": m.class_id,
                "final_grade": grade_data["final_grade"],
                "letter_grade": grade_data["letter_grade"],
            }
        )

    gpa = round(total_weighted / total_weight, 1) if total_weight > 0 else 0
    return {
        "gpa": gpa,
        "letter_grade": _letter_grade(gpa),
        "classes": class_grades,
    }


def _letter_grade(score: float) -> str:
    if score >= 90:
        return "ممتاز"
    if score >= 80:
        return "جيد جداً"
    if score >= 70:
        return "جيد"
    if score >= 60:
        return "مقبول"
    return "راسب"


def generate_report_card(student_id: int, class_id: int) -> dict:
    """تقرير شامل لطالب في صف معين."""
    from app.models.class_room import ClassRoom
    from app.models.progress import StudentProgress
    from app.models.user import User

    student = db.session.get(User, student_id)
    class_room = db.session.get(ClassRoom, class_id)
    grade_data = calculate_student_grade(student_id, class_id)

    completed_lessons = StudentProgress.query.filter_by(
        student_id=student_id, class_id=class_id, status="completed"
    ).count()
    total_lessons = (
        StudentProgress.query.filter_by(class_id=class_id).with_entities(db.func.count(StudentProgress.id)).scalar()
        or 0
    )

    avg_progress = (
        db.session.query(db.func.avg(StudentProgress.progress_pct))
        .filter(
            StudentProgress.student_id == student_id,
            StudentProgress.class_id == class_id,
        )
        .scalar()
        or 0
    )

    return {
        "student": student,
        "class_room": class_room,
        "grade_data": grade_data,
        "completed_lessons": completed_lessons,
        "total_lessons": total_lessons,
        "avg_progress": round(float(avg_progress), 1),
    }


def render_report_card_html(student_id: int, class_id: int) -> str:
    """render report card to HTML string for PDF conversion."""
    from flask import render_template

    data = generate_report_card(student_id, class_id)
    return render_template("grades/report_card.html", **data)


def render_report_card_pdf(student_id: int, class_id: int) -> bytes | None:
    """render report card HTML → PDF."""
    try:
        from xhtml2pdf import pisa

        html = render_report_card_html(student_id, class_id)
        pdf_bytes = pisa.CreatePDF(html).dest
        return pdf_bytes
    except ImportError:
        return None
