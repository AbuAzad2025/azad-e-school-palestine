"""خدمات التصدير — تصدير بيانات إلى Excel."""

import io

from openpyxl import Workbook

from app.models.class_room import ClassMember
from app.models.gradebook import GradeEntry, GradeItem
from app.models.progress import StudentProgress


def export_students_excel(class_id: int) -> bytes:
    """تصدير قائمة الطلاب إلى Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = "الطلاب"
    ws.append(["الاسم", "البريد الإلكتروني", "تاريخ الانضمام", "الحالة"])

    members = ClassMember.query.filter_by(class_id=class_id).all()
    for m in members:
        ws.append(
            [
                m.user.name_ar or "",
                m.user.email,
                m.joined_at.strftime("%Y-%m-%d") if m.joined_at else "",
                "نشط" if m.status == "active" else m.status,
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def export_grades_excel(class_id: int) -> bytes:
    """تصدير درجات الصف إلى Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = "الدرجات"

    items = GradeItem.query.filter_by(class_id=class_id).order_by(GradeItem.id).all()
    header = ["الاسم", "البريد الإلكتروني"]
    for item in items:
        header.append(f"{item.title} (/{item.max_mark or '?'})")
    ws.append(header)

    members = ClassMember.query.filter_by(class_id=class_id, status="active").all()
    entries = {}
    if items:
        rows = GradeEntry.query.filter(GradeEntry.grade_item_id.in_([i.id for i in items])).all()
        entries = {(r.student_id, r.grade_item_id): r for r in rows}

    for m in members:
        row = [m.user.name_ar or "", m.user.email]
        for item in items:
            entry = entries.get((m.user_id, item.id))
            row.append(float(entry.mark) if entry and entry.mark is not None else "")
        ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def export_progress_excel(class_id: int) -> bytes:
    """تصدير تقدم الطلاب إلى Excel."""
    wb = Workbook()
    ws = wb.active
    ws.title = "التقدم"
    ws.append(["الاسم", "البريد الإلكتروني", "الدرس", "الحالة", "الوقت (دقيقة)", "النسبة %"])

    progress = StudentProgress.query.filter_by(class_id=class_id).all()
    for p in progress:
        ws.append(
            [
                p.student.name_ar or "",
                p.student.email,
                p.lesson.title if p.lesson else f"درس #{p.lesson_id}",
                {"not_started": "لم يبدأ", "in_progress": "قيد التنفيذ", "completed": "مكتمل"}[p.status],
                p.seconds_spent // 60,
                p.progress_pct,
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()
