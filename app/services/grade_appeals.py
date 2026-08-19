"""خدمات اعتراضات الدرجات."""

from datetime import UTC, datetime

from app.core.db import tx
from app.extensions import db
from app.models.gradebook import GradeAppeal


def submit_appeal(submission_id: int, student_id: int, reason: str) -> GradeAppeal | None:
    reason = (reason or "").strip()
    if not reason:
        return None
    existing = GradeAppeal.query.filter_by(submission_id=submission_id, student_id=student_id).first()
    if existing:
        return None

    def _submit():
        appeal = GradeAppeal(submission_id=submission_id, student_id=student_id, reason=reason)
        db.session.add(appeal)
        return appeal

    return tx(_submit)


def review_appeal(appeal_id: int, status: str, response: str | None, reviewed_by: int) -> GradeAppeal | None:
    if status not in ("approved", "rejected", "reviewing"):
        return None

    def _review():
        a = db.session.get(GradeAppeal, appeal_id)
        if not a:
            return None
        a.status = status
        a.teacher_response = response
        a.reviewed_by = reviewed_by
        a.reviewed_at = datetime.now(UTC)
        return a

    return tx(_review)


def get_student_appeals(student_id: int) -> list[GradeAppeal]:
    return GradeAppeal.query.filter_by(student_id=student_id).order_by(GradeAppeal.created_at.desc()).all()


def get_class_appeals(class_id: int) -> list[GradeAppeal]:
    from app.models.gradebook import Submission

    return (
        GradeAppeal.query.join(Submission, GradeAppeal.submission_id == Submission.id)
        .filter(Submission.assignment.has(class_id=class_id))
        .order_by(GradeAppeal.created_at.desc())
        .all()
    )


def get_pending_appeals() -> list[GradeAppeal]:
    return GradeAppeal.query.filter_by(status="pending").order_by(GradeAppeal.created_at.desc()).all()
