"""Auto-grading — async tasks for heavy quiz/assignment grading operations.

P4-10: Auto-grading of heavy quizzes as background tasks.
P4-11: Batch grading for assignments with rubric evaluation.
P4-12: Grade computation results stored atomically via tx().
"""

from __future__ import annotations

from app.tasks import _HAS_CELERY

if not _HAS_CELERY:
    raise ImportError("Celery is required for app.tasks.grading")

from decimal import Decimal

from app.tasks import ContextTask, celery_app


@celery_app.task(base=ContextTask, bind=True, max_retries=3, time_limit=300)
def auto_grade_quiz_attempt(
    self,
    attempt_id: int,
) -> dict:
    """Auto-grade a quiz attempt (MCQ + fill-in-the-blank).

    Processes all answers in the attempt, calculates the score,
    and updates the attempt status atomically.

    Args:
        attempt_id: The QuizAttempt ID to grade.

    Returns:
        {"attempt_id": int, "score": float, "status": "completed" | "failed"}
    """
    from app.core.db import TxError, tx
    from app.core.logging import get_logger
    from app.extensions import db
    from app.models.assessment import Answer, QuizAttempt

    logger = get_logger(__name__)
    logger.info("auto_grading_started", attempt_id=attempt_id)

    try:
        attempt = db.session.get(QuizAttempt, attempt_id)
        if not attempt:
            return {"attempt_id": attempt_id, "score": 0, "status": "failed", "error": "Attempt not found"}

        if attempt.status != "submitted":
            return {"attempt_id": attempt_id, "score": 0, "status": "skipped", "error": "Not in submitted status"}

        # Fetch all answers for this attempt
        answers = Answer.query.filter_by(attempt_id=attempt_id).all()
        questions = {q.id: q for q in attempt.quiz.questions}

        total_score = Decimal("0")

        def _grade():
            nonlocal total_score
            for answer in answers:
                question = questions.get(answer.question_id)
                if question is None or answer.answer is None:
                    continue

                # Grade MCQ
                if question.question_type in ("mcq", "true_false"):
                    correct = str(question.correct_answer).strip().lower()
                    given = str(answer.answer).strip().lower()
                    answer.is_correct = correct == given
                    answer.awarded_mark = float(question.marks) if answer.is_correct else 0
                    if answer.is_correct:
                        total_score += Decimal(str(question.marks))

                # Grade fill-in-the-blank (exact match, case-insensitive)
                elif question.question_type == "fill_blank":
                    correct = str(question.correct_answer).strip().lower()
                    given = str(answer.answer).strip().lower()
                    answer.is_correct = correct == given
                    answer.awarded_mark = float(question.marks) if answer.is_correct else 0
                    if answer.is_correct:
                        total_score += Decimal(str(question.marks))

                # Essay — left for manual grading
                elif question.question_type == "essay":
                    answer.is_correct = None  # Pending manual grade
                    answer.awarded_mark = None

            # Update attempt score and status
            attempt.score = float(total_score.quantize(Decimal("0.01")))
            attempt.status = "graded"

        tx(_grade)

        logger.info(
            "auto_grading_completed",
            attempt_id=attempt_id,
            score=attempt.score,
        )

        return {
            "attempt_id": attempt_id,
            "score": attempt.score,
            "status": "completed",
            "error": None,
        }

    except TxError as exc:
        logger.error("auto_grading_tx_error", attempt_id=attempt_id, error=str(exc))
        return {"attempt_id": attempt_id, "score": 0, "status": "failed", "error": str(exc)}
    except Exception as exc:
        logger.exception("auto_grading_failed", attempt_id=attempt_id)
        return {"attempt_id": attempt_id, "score": 0, "status": "failed", "error": str(exc)}


@celery_app.task(base=ContextTask, bind=True, max_retries=2, time_limit=600)
def batch_grade_quiz(
    self,
    quiz_id: int,
) -> dict:
    """Batch auto-grade all submitted attempts for a quiz.

    Processes each attempt independently — one failure doesn't block others.

    Args:
        quiz_id: The Quiz ID to grade all attempts for.

    Returns:
        {"quiz_id": int, "total": int, "graded": int, "failed": int}
    """
    from app.core.logging import get_logger
    from app.models.assessment import QuizAttempt

    logger = get_logger(__name__)
    logger.info("batch_grading_started", quiz_id=quiz_id)

    # Fetch all submitted (ungraded) attempts
    attempts = QuizAttempt.query.filter_by(quiz_id=quiz_id, status="submitted").all()

    if not attempts:
        return {"quiz_id": quiz_id, "total": 0, "graded": 0, "failed": 0}

    graded = 0
    failed = 0

    for attempt in attempts:
        result = auto_grade_quiz_attempt.delay(attempt.id)
        # For synchronous-style batch (within a task), we wait for each
        # For truly parallel, use group() and collect results
        try:
            task_result = result.get(timeout=120)
            if task_result.get("status") == "completed":
                graded += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    logger.info(
        "batch_grading_completed",
        quiz_id=quiz_id,
        total=len(attempts),
        graded=graded,
        failed=failed,
    )

    return {
        "quiz_id": quiz_id,
        "total": len(attempts),
        "graded": graded,
        "failed": failed,
    }


@celery_app.task(base=ContextTask, bind=True, max_retries=2, time_limit=300)
def batch_update_gradebook(
    self,
    class_id: int,
    grade_item_id: int,
    entries: list[dict],
) -> dict:
    """Batch update grade entries for a grade item.

    Args:
        class_id: Target class.
        grade_item_id: Target grade item.
        entries: List of {"student_id": int, "mark": float, "note": str | None}

    Returns:
        {"updated": int, "status": "completed" | "failed"}
    """
    from app.core.db import TxError, tx
    from app.core.logging import get_logger
    from app.extensions import db
    from app.models.gradebook import GradeEntry, GradeItem

    logger = get_logger(__name__)
    logger.info(
        "batch_gradebook_update_started",
        class_id=class_id,
        grade_item_id=grade_item_id,
        entry_count=len(entries),
    )

    try:
        grade_item = db.session.get(GradeItem, grade_item_id)
        if not grade_item or grade_item.class_id != class_id:
            return {"updated": 0, "status": "failed", "error": "Grade item not found or wrong class"}

        def _batch_update():
            updated = 0
            for entry_data in entries:
                student_id = entry_data["student_id"]
                mark = entry_data.get("mark")
                note = entry_data.get("note")

                # Upsert: find existing or create new
                existing = GradeEntry.query.filter_by(
                    grade_item_id=grade_item_id,
                    student_id=student_id,
                ).first()

                if existing:
                    existing.mark = mark
                    existing.recorded_by = entry_data.get("recorded_by")
                    if note is not None:
                        existing.note = note
                else:
                    db.session.add(
                        GradeEntry(
                            grade_item_id=grade_item_id,
                            student_id=student_id,
                            mark=mark,
                            recorded_by=entry_data.get("recorded_by"),
                            note=note,
                        )
                    )
                updated += 1
            return updated

        updated_count = tx(_batch_update)

        logger.info(
            "batch_gradebook_update_completed",
            class_id=class_id,
            grade_item_id=grade_item_id,
            updated=updated_count,
        )

        return {"updated": updated_count, "status": "completed", "error": None}

    except TxError as exc:
        logger.error("batch_gradebook_tx_error", error=str(exc))
        return {"updated": 0, "status": "failed", "error": str(exc)}
    except Exception as exc:
        logger.exception("batch_gradebook_update_failed")
        return {"updated": 0, "status": "failed", "error": str(exc)}
