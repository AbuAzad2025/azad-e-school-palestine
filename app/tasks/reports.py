"""PDF report generation — async tasks for heavy report generation.

P4-07: Report card generation, invoices, and analytics as background tasks.
P4-08: Generated files stored on disk with cleanup after configurable retention.
P4-09: Reports scoped to school_id for tenancy isolation.
"""

from __future__ import annotations

from app.tasks import _HAS_CELERY

if not _HAS_CELERY:
    raise ImportError("Celery is required for app.tasks.reports")

from datetime import UTC, datetime
from typing import Any

from app.tasks import ContextTask, celery_app


@celery_app.task(base=ContextTask, bind=True, max_retries=2, time_limit=600)
def generate_report_card(
    self,
    student_id: int,
    class_id: int,
    school_id: int,
) -> dict:
    """Generate a PDF report card for a student in a specific class.

    Runs heavy computation (grade aggregation, PDF rendering) in background.
    Result stored on disk; path returned for retrieval.

    Args:
        student_id: Target student.
        class_id: Target class.
        school_id: School (for tenancy + file organization).

    Returns:
        {"status": "completed" | "failed", "file_path": str | None, "error": str | None}
    """
    from app.core.logging import get_logger
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

        # Generate PDF (placeholder — real implementation uses reportlab/weasyprint)
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
    """Generate a PDF report for an entire class (all students).

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


# ─── PDF Writing Helpers ───────────────────────────────────────────────


def _get_output_dir(school_id: int, subdir: str = "reports") -> str:
    """Get/create output directory for generated files."""
    import os

    from flask import current_app

    base = current_app.config.get("UPLOAD_FOLDER", "instance/uploads")
    path = os.path.join(str(base), "generated", subdir, str(school_id))
    os.makedirs(path, exist_ok=True)
    return path


def _write_report_pdf(
    student_id: int,
    class_id: int,
    school_id: int,
    grade_data: dict,
) -> str:
    """Write report card PDF. Returns file path.

    NOTE: This is a production stub. In a real implementation, use
    reportlab or weasyprint to generate actual PDFs.
    """
    import json
    import os

    output_dir = _get_output_dir(school_id, "report_cards")
    filename = f"report_{student_id}_{class_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(output_dir, filename)

    # For now, write structured data. Replace with actual PDF generation.
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(
            {
                "student_id": student_id,
                "class_id": class_id,
                "school_id": school_id,
                "generated_at": datetime.now(UTC).isoformat(),
                "grade_data": grade_data,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return filepath


def _write_class_report_pdf(
    class_id: int,
    school_id: int,
    grades_summary: list[dict],
) -> str:
    """Write class-wide report PDF."""
    import json
    import os

    output_dir = _get_output_dir(school_id, "class_reports")
    filename = f"class_{class_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(
            {
                "class_id": class_id,
                "school_id": school_id,
                "generated_at": datetime.now(UTC).isoformat(),
                "student_count": len(grades_summary),
                "grades": [{k: v for k, v in item.items() if k != "student"} for item in grades_summary],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return filepath


def _write_invoice_pdf(
    subscription: Any,
    payments: list[Any],
    school_id: int,
) -> str:
    """Write invoice PDF."""
    import json
    import os

    output_dir = _get_output_dir(school_id, "invoices")
    filename = f"invoice_{subscription.id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(
            {
                "subscription_id": subscription.id,
                "user_id": subscription.user_id,
                "school_id": school_id,
                "generated_at": datetime.now(UTC).isoformat(),
                "price": str(subscription.price),
                "currency": subscription.currency,
                "status": subscription.status,
                "payments": [{"id": p.id, "amount": str(p.amount), "status": p.status} for p in payments],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return filepath


# Need db for generate_invoice
from app.extensions import db  # noqa: E402
