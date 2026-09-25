"""كشوف الدرجات — GPA + تقرير الطالب.

توليد PDF عبر reportlab (platypus) عبر البنية المشتركة app/core/pdf.py —
خط عربي مدمج + تشكيل RTL. قصة بطاقة الدرجات الواحدة (build_report_card_story)
تُستخدم من الخدمة المتزامنة (render_report_card_pdf) ومن مهمة الخلفية
(app.tasks.reports) حتى يتطابق الإنتاجان دائماً.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.extensions import db
from app.models.class_room import ClassMember
from app.services.grade_calc import calculate_student_grade

logger = get_logger(__name__)


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


def build_report_card_story(
    story: list,
    student_id: int,
    class_id: int,
    grade_data: dict,
    *,
    student=None,
    class_room=None,
    progress: dict | None = None,
) -> None:
    """تعبئة قصة platypus ببطاقة درجات الطالب — المصدر الوحيد للتخطيط.

    تُستخدم من render_report_card_pdf (متزامن) ومن app.tasks.reports (خلفي)
    عبر _write_report_pdf — بلا تكرار.

    Args:
        story: قصة platypus فارغة من blank_pdf_document().
        student_id / class_id: معرّفات السطر التعريفي LTR.
        grade_data: ناتج calculate_student_grade (categories/final_grade/
            letter_grade) — وقد يحمل "student_name" المحقون من المهمة.
        student: كائن User اختياري (المسار المتزامن) لعرض الاسم/البريد.
        class_room: كائن ClassRoom اختياري لعرض الصف/المادة/المعلم.
        progress: {completed_lessons, total_lessons, avg_progress} اختياري.
    """
    from reportlab.lib.units import mm

    from app.core.pdf import (
        register_arabic_font,
        shape_arabic_deep,
        story_meta,
        story_subtitle,
        story_table,
        story_title,
    )

    font = register_arabic_font()

    student_name = (
        getattr(student, "name_ar", None)
        or grade_data.get("student_name")
        or getattr(student, "email", "")
        or str(student_id)
    )
    class_title = getattr(class_room, "name", None) or ""
    subject = getattr(class_room, "subject", None)
    subject_name = getattr(subject, "name_ar", "") or ""
    teacher = getattr(class_room, "teacher", None)
    teacher_name = getattr(teacher, "name_ar", "") or "—"

    story_title(story, shape_arabic_deep("تقرير الدرجات"), font)
    story_subtitle(story, shape_arabic_deep(class_title or subject_name or "—"), font)
    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    story_meta(story, f"Student #{student_id} | Class #{class_id} | {now_utc}")

    info_rows = [
        [shape_arabic_deep("الاسم"), shape_arabic_deep(str(student_name))],
        [shape_arabic_deep("البريد"), str(getattr(student, "email", "") or "—")],
        [shape_arabic_deep("المادة"), shape_arabic_deep(subject_name or "—")],
        [shape_arabic_deep("المعلم"), shape_arabic_deep(str(teacher_name))],
    ]
    story_table(story, info_rows, [40 * mm, 80 * mm], font)

    story_subtitle(story, shape_arabic_deep("الدرجات حسب الأقسام"), font)
    categories = grade_data.get("categories", []) if isinstance(grade_data, dict) else []
    if categories:
        rows = [
            [
                shape_arabic_deep("القسم"),
                shape_arabic_deep("الوزن"),
                shape_arabic_deep("النسبة"),
                shape_arabic_deep("الدرجة الموزونة"),
            ],
        ]
        for cat in categories:
            rows.append(
                [
                    shape_arabic_deep(str(cat.get("name", "—"))),
                    f"{float(cat.get('weight', 0)):.0%}",
                    f"{float(cat.get('category_pct', 0)):.1f}%",
                    f"{float(cat.get('weighted_score', 0)):.2f}",
                ]
            )
        story_table(story, rows, [60 * mm, 30 * mm, 30 * mm, 40 * mm], font)
    else:
        story_subtitle(story, shape_arabic_deep("لا توجد درجات مسجلة بعد"), font)

    final_grade = grade_data.get("final_grade", "—") if isinstance(grade_data, dict) else "—"
    letter = grade_data.get("letter_grade", "") if isinstance(grade_data, dict) else ""
    summary_rows = [
        [shape_arabic_deep("الدرجة النهائية"), str(final_grade)],
        [shape_arabic_deep("التقدير"), shape_arabic_deep(str(letter))],
    ]
    if progress:
        summary_rows.append([shape_arabic_deep("متوسط التقدم"), f"{float(progress.get('avg_progress', 0)):.1f}%"])
        summary_rows.append(
            [
                shape_arabic_deep("دروس مكتملة"),
                f"{progress.get('completed_lessons', 0)} / {progress.get('total_lessons', 0)}",
            ]
        )
    story_table(story, summary_rows, [70 * mm, 50 * mm], font)


def render_report_card_pdf(student_id: int, class_id: int) -> bytes | None:
    """بطاقة درجات PDF حقيقية عبر reportlab (لا HTML وسيط).

    Returns:
        bytes الخام عند النجاح؛ None إذا لم يوجد الطالب/الصف أو فشل البناء.
    """
    try:
        data = generate_report_card(student_id, class_id)
        if not data.get("student") or not data.get("class_room"):
            return None

        from app.core.pdf import blank_pdf_document, build_pdf_bytes, write_pdf_file

        doc, story = blank_pdf_document()
        build_report_card_story(
            story,
            student_id,
            class_id,
            data["grade_data"],
            student=data.get("student"),
            class_room=data.get("class_room"),
            progress={k: data.get(k, 0) for k in ("completed_lessons", "total_lessons", "avg_progress")},
        )
        pdf = build_pdf_bytes(doc, story)
    except Exception:
        logger.exception("report_card_pdf_generation_failed", student_id=student_id, class_id=class_id)
        return None

    write_pdf_file("report_cards", f"report_{student_id}_{class_id}", pdf)
    return pdf
