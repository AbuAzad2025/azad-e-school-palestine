"""كشوف الدرجات — GPA + تقرير الطالب."""

from app.extensions import db
from app.models.class_room import ClassMember
from app.services.grade_calc import calculate_student_grade


def calculate_gpa(student_id: int, school_id: int) -> dict:
    """حساب المعدل التراكمي لطالب في مدرسة عبر جميع صفوفه."""
    memberships = (
        ClassMember.query.join(ClassMember.class_room)
        .filter(
            ClassMember.user_id == student_id,
            ClassMember.status == "active",
        )
        .all()
    )

    # Batch: جلب جميع البنود لكل الصفوف في استعلام واحد
    class_ids = [m.class_id for m in memberships]

    from sqlalchemy.orm import selectinload

    from app.models.gradebook import GradeCategory, GradeEntry, GradeItem

    all_categories = (
        GradeCategory.query.filter(GradeCategory.class_id.in_(class_ids or [0]))
        .options(selectinload(GradeCategory.items))
        .order_by(GradeCategory.id.asc())
        .all()
    )
    categories_by_class: dict[int, list] = {}
    for cat in all_categories:
        categories_by_class.setdefault(cat.class_id, []).append(cat)

    # Batch: جلب جميع الدرجات للطالب في كل الصفوف
    all_items = GradeItem.query.filter(GradeItem.class_id.in_(class_ids or [0])).all()
    item_ids = [i.id for i in all_items]
    entries = {}
    if item_ids:
        rows = GradeEntry.query.filter(
            GradeEntry.grade_item_id.in_(item_ids),
            GradeEntry.student_id == student_id,
        ).all()
        entries = {r.grade_item_id: r for r in rows}

    # حساب الدرجة لكل صف من البيانات المحمّلة
    total_weighted = 0.0
    total_weight = 0.0
    class_grades = []

    for m in memberships:
        class_cats = categories_by_class.get(m.class_id, [])
        cat_total_weighted = 0.0
        cat_total_weight = 0.0

        for cat in class_cats:
            cat_weight = float(cat.weight) if cat.weight else 0
            cat_total_marks = 0.0
            cat_earned_marks = 0.0

            for item in cat.items:
                entry = entries.get(item.id)
                max_mark = float(item.max_mark) if item.max_mark else 0
                earned = float(entry.mark) if entry and entry.mark is not None else None
                if earned is not None and max_mark > 0:
                    cat_total_marks += max_mark
                    cat_earned_marks += earned

            category_pct = round((cat_earned_marks / cat_total_marks * 100), 1) if cat_total_marks > 0 else 0
            weighted_score = round(category_pct * cat_weight, 2)
            cat_total_weighted += weighted_score
            cat_total_weight += cat_weight

        final = round(cat_total_weighted / cat_total_weight, 1) if cat_total_weight > 0 else 0
        total_weighted += cat_total_weighted
        total_weight += cat_total_weight
        class_grades.append(
            {
                "class_id": m.class_id,
                "final_grade": final,
                "letter_grade": _letter_grade(final),
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
