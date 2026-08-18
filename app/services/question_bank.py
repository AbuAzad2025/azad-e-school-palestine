"""بنك الأسئلة: إنشاء، بحث، استيراد."""

from app.core.db import tx
from app.extensions import db
from app.models.assessment import Question, Quiz
from app.models.question_bank import QuestionBank


def create_bank_question(
    teacher_id: int,
    school_id: int,
    question_text: str,
    question_type: str,
    subject_id: int | None = None,
    options=None,
    correct_answer=None,
    difficulty: int = 3,
    tags: list | None = None,
    is_shared: bool = False,
) -> tuple[QuestionBank | None, str | None]:
    question_text = (question_text or "").strip()
    if not question_text:
        return None, "نص السؤال مطلوب."
    if question_type not in ("mcq", "true_false", "essay"):
        return None, "نوع السؤال غير صالح."
    if not (1 <= difficulty <= 5):
        return None, "الصعوبة يجب أن تكون بين 1 و 5."

    def _create():
        bq = QuestionBank(
            teacher_id=teacher_id,
            school_id=school_id,
            subject_id=subject_id,
            question_text=question_text,
            question_type=question_type,
            options=options,
            correct_answer=correct_answer,
            difficulty=difficulty,
            tags=tags,
            is_shared=is_shared,
        )
        db.session.add(bq)
        return bq

    return tx(_create), None


def list_bank_questions(
    teacher_id: int,
    subject_id: int | None = None,
    question_type: str | None = None,
    difficulty: int | None = None,
) -> list[QuestionBank]:
    q = QuestionBank.query.filter_by(teacher_id=teacher_id)
    if subject_id is not None:
        q = q.filter_by(subject_id=subject_id)
    if question_type is not None:
        q = q.filter_by(question_type=question_type)
    if difficulty is not None:
        q = q.filter_by(difficulty=difficulty)
    return q.order_by(QuestionBank.created_at.desc()).all()


def update_bank_question(
    question_id: int,
    teacher_id: int,
    **kwargs,
) -> tuple[QuestionBank | None, str | None]:
    bq = db.session.get(QuestionBank, question_id)
    if not bq:
        return None, "السؤال غير موجود."
    if bq.teacher_id != teacher_id:
        return None, "ليس لديك صلاحية تعديل هذا السؤال."
    allowed = {
        "question_text",
        "question_type",
        "subject_id",
        "options",
        "correct_answer",
        "difficulty",
        "tags",
        "is_shared",
    }
    for key, val in kwargs.items():
        if key in allowed:
            setattr(bq, key, val)

    def _save():
        db.session.flush()

    tx(_save)
    return bq, None


def delete_bank_question(question_id: int, teacher_id: int) -> tuple[bool, str | None]:
    bq = db.session.get(QuestionBank, question_id)
    if not bq:
        return False, "السؤال غير موجود."
    if bq.teacher_id != teacher_id:
        return False, "ليس لديك صلاحية حذف هذا السؤال."

    def _del():
        db.session.delete(bq)

    tx(_del)
    return True, None


def import_to_quiz(quiz: Quiz, question_ids: list[int], teacher_id: int) -> tuple[int, str | None]:
    """استيراد أسئلة من البنك إلى اختبار. يعيد عدد الأسئلة المستوردة."""
    if not question_ids:
        return 0, "لم تُحدد أسئلة."
    bank_questions = QuestionBank.query.filter(
        QuestionBank.id.in_(question_ids),
        QuestionBank.teacher_id == teacher_id,
    ).all()
    if not bank_questions:
        return 0, "لم يتم العثور على أسئلة صالحة."
    max_order = max((q.sort_order or 0 for q in quiz.questions), default=0)

    def _import():
        count = 0
        for bq in bank_questions:
            db.session.add(
                Question(
                    quiz_id=quiz.id,
                    type=bq.question_type,
                    prompt=bq.question_text,
                    options=bq.options,
                    correct_answer=bq.correct_answer,
                    mark=1.0,
                    sort_order=max_order + count + 1,
                )
            )
            count += 1
        return count

    count = tx(_import)
    return count, None
