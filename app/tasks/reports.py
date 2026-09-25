"""PDF report generation — async tasks for heavy report generation.

P4-07: Report card generation, invoices, and analytics as background tasks.
P4-08: Generated files stored on disk with cleanup after configurable retention.
P4-09: Reports scoped to school_id for tenancy isolation.

التنفيذ الحقيقي: reportlab (platypus) مباشرة عبر البنية المشتركة في
app/core/pdf.py — خط عربي مدمج + تشكيل RTL + كتابة ذرّية. الملفات تُكتب
تحت instance/uploads/generated/<subdir>/<school_id>/ — خارج المجلد العام (D7).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.tasks import _HAS_CELERY

if not _HAS_CELERY:
    raise ImportError("Celery is required for app.tasks.reports")

from app.tasks import ContextTask, celery_app


@celery_app.task(base=ContextTask, bind=True, max_retries=2, time_limit=600)
def generate_report_card(
    self,
    student_id: int,
    class_id: int,
    school_id: int,
) -> dict:
    """Generate an Arabic PDF report card for a student in a specific class.

    Runs heavy computation (grade aggregation, PDF rendering) in background.
    Result stored under generated/report_cards/<school_id>/; path returned.

    Args:
        student_id: Target student.
        class_id: Target class.
        school_id: School (for tenancy + file organization).

    Returns:
        {"status": "completed" | "failed", "file_path": str | None, "error": str | None}
    """
    from app.core.logging import get_logger
    from app.extensions import db
    from app.models.user import User
    from app.services.grade_calc import calculate_student_grade

    logger = get_logger(__name__)
    logger.info(
        "report_card_generation_started",
        student_id=student_id,
        class_id=class_id,
        school_id=school_id,
    )

    try:
        # Calculate grades (heavy query)
        grade_data = calculate_student_grade(student_id, class_id)

        # Student display name for the PDF header (extra key — harmless)
        student = db.session.get(User, student_id)
        grade_data["student_name"] = getattr(student, "name_ar", None) or str(student_id)

        # Render real PDF via shared infra (Arabic font + atomic write)
        output_path = _write_report_pdf(
            student_id=student_id,
            class_id=class_id,
            school_id=school_id,
            grade_data=grade_data,
        )

        logger.info(
            "report_card_generated",
            student_id=student_id,
            class_id=class_id,
            file_path=output_path,
        )

        return {
            "status": "completed",
            "file_path": output_path,
            "error": None,
        }
    except Exception as exc:
        logger.exception(
            "report_card_generation_failed",
            student_id=student_id,
            class_id=class_id,
        )
        return {
            "status": "failed",
            "file_path": None,
            "error": str(exc),
        }


@celery_app.task(base=ContextTask, bind=True, max_retries=2, time_limit=600)
def generate_class_report(
    self,
    class_id: int,
    school_id: int,
) -> dict:
    """Generate a PDF grade report for an entire class (all students).

    Args:
        class_id: Target class.
        school_id: School (for tenancy).

    Returns:
        {"status": "completed" | "failed", "file_path": str | None, "student_count": int}
    """
    from app.core.logging import get_logger
    from app.models.class_room import ClassMember
    from app.services.grade_calc import class_grades_summary

    logger = get_logger(__name__)
    logger.info("class_report_generation_started", class_id=class_id)

    try:
        # Get all students in the class
        members = ClassMember.query.filter_by(class_id=class_id, status="active").all()
        student_ids = [m.user_id for m in members]

        # Calculate all grades in batch (single query — no N+1)
        grades_summary = class_grades_summary(class_id)

        # Generate PDF
        output_path = _write_class_report_pdf(
            class_id=class_id,
            school_id=school_id,
            grades_summary=grades_summary,
        )

        logger.info(
            "class_report_generated",
            class_id=class_id,
            student_count=len(student_ids),
            file_path=output_path,
        )

        return {
            "status": "completed",
            "file_path": output_path,
            "student_count": len(student_ids),
            "error": None,
        }
    except Exception as exc:
        logger.exception("class_report_generation_failed", class_id=class_id)
        return {
            "status": "failed",
            "file_path": None,
            "student_count": 0,
            "error": str(exc),
        }


@celery_app.task(base=ContextTask, bind=True, max_retries=2, time_limit=300)
def generate_invoice(
    self,
    subscription_id: int,
    school_id: int,
) -> dict:
    """Generate a PDF invoice for a subscription.

    Reuses the shared invoice service (numbering + payment summary) so the
    background artifact matches the on-screen invoice data exactly.

    Args:
        subscription_id: Target subscription.
        school_id: School (for tenancy + currency).

    Returns:
        {"status": "completed" | "failed", "file_path": str | None}
    """
    from app.core.logging import get_logger
    from app.models.billing import ManualPayment, Subscription

    logger = get_logger(__name__)
    logger.info("invoice_generation_started", subscription_id=subscription_id)

    try:
        from app.extensions import db

        sub = db.session.get(Subscription, subscription_id)
        if not sub:
            return {"status": "failed", "file_path": None, "error": "Subscription not found"}

        payments = ManualPayment.query.filter_by(subscription_id=subscription_id).all()

        output_path = _write_invoice_pdf(
            subscription=sub,
            payments=payments,
            school_id=school_id,
        )

        return {"status": "completed", "file_path": output_path, "error": None}
    except Exception as exc:
        logger.exception("invoice_generation_failed", subscription_id=subscription_id)
        return {"status": "failed", "file_path": None, "error": str(exc)}


# ─── PDF Writers (real rendering via app/core/pdf.py) ─────────────────


def _write_report_pdf(
    student_id: int,
    class_id: int,
    school_id: int,
    grade_data: dict,
) -> str:
    """Render the report card PDF for one student. Returns file path.

    التخطيط الوحيد لبطاقة الدرجات يعيش في app/services/report_card.py::
    build_report_card_story — هذه مجرد مهمة الخلفية الملفّة عليه.
    """
    from app.core.pdf import blank_pdf_document, build_pdf_bytes, write_pdf_file
    from app.services.report_card import build_report_card_story

    doc, story = blank_pdf_document()
    build_report_card_story(story, student_id, class_id, grade_data)
    return write_pdf_file(
        "report_cards", f"report_{student_id}_{class_id}", build_pdf_bytes(doc, story), school_id=school_id
    )


def _write_class_report_pdf(
    class_id: int,
    school_id: int,
    grades_summary: list[dict],
) -> str:
    """Render the class-wide grade report PDF. Returns file path."""
    from reportlab.lib.units import mm

    from app.core.pdf import (
        blank_pdf_document,
        build_pdf_bytes,
        register_arabic_font,
        shape_arabic,
        shape_arabic_deep,
        story_meta,
        story_subtitle,
        story_table,
        story_title,
        write_pdf_file,
    )

    font = register_arabic_font()

    rows = [
        [
            shape_arabic_deep("#"),
            shape_arabic_deep("الطالب"),
            shape_arabic_deep("الدرجة النهائية"),
            shape_arabic_deep("التقدير"),
        ]
    ]
    for idx, item in enumerate(grades_summary, start=1):
        student = item.get("student")
        name = getattr(student, "name_ar", None) or str(item.get("student_id"))
        rows.append(
            [
                str(idx),
                shape_arabic_deep(str(name)),
                f"{float(item.get('final_grade') or 0):.1f}",
                shape_arabic_deep(str(item.get("letter_grade", ""))),
            ]
        )

    doc, story = blank_pdf_document()
    story_title(story, shape_arabic_deep("تقرير درجات الصف"), font)
    story_subtitle(story, shape_arabic(f"عدد الطلاب: {len(grades_summary)}"), font)
    story_meta(story, f"Class #{class_id} | {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")

    if len(rows) > 1:
        story_table(story, rows, [15 * mm, 75 * mm, 35 * mm, 35 * mm], font)
    else:
        story_subtitle(story, shape_arabic_deep("لا يوجد طلاب في هذا الصف"), font)

    return write_pdf_file("class_reports", f"class_{class_id}", build_pdf_bytes(doc, story), school_id=school_id)


def _write_invoice_pdf(
    subscription: Any,
    payments: list[Any],
    school_id: int,
) -> str:
    """Render the invoice PDF. Returns file path.

    التخطيط الوحيد للفاتورة يعيش في app/services/invoice.py::
    build_invoice_story — هذه مجرد مهمة الخلفية الملفّة عليه.
    """
    from app.core.pdf import blank_pdf_document, build_pdf_bytes, write_pdf_file
    from app.services.invoice import build_invoice_story

    doc, story = blank_pdf_document()
    build_invoice_story(story, subscription, payments)
    data = build_pdf_bytes(doc, story)
    return write_pdf_file("invoices", f"invoice_{subscription.id}", data, school_id=school_id)
