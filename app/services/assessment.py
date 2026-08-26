"""خدمات التقييم: اختبارات، أسئلة، محاولات، تصحيح آلي ونتائج.

P1-05/06/11: قيد جزئي على المحاولات المفتوحة، قفل صفوف عند التسليم،
وفرض مؤقت الاختبار من الخادم (مع مهلة سماح قابلة للضبط).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from app.core.db import TxError, tx
from app.core.i18n import _
from app.extensions import db
from app.models.assessment import Answer, Question, Quiz, QuizAttempt


def create_quiz(
    class_id: int,
    title: str,
    duration_min: int | None = None,
    attempts_allowed: int = 1,
    shuffle: bool = False,
    show_answers_after: bool = False,
    created_by: int | None = None,
) -> tuple[Quiz | None, str | None]:
    title = (title or "").strip()
    if not title:
        return None, _("عنوان الاختبار مطلوب.")

    def _create():
        quiz = Quiz(
            class_id=class_id,
            title=title,
            duration_min=duration_min,
            attempts_allowed=attempts_allowed,
            shuffle=shuffle,
            show_answers_after=show_answers_after,
            created_by=created_by,
        )
        db.session.add(quiz)
        return quiz

    return tx(_create), None


def list_quizzes(class_id: int):
    return (
        Quiz.query.filter_by(class_id=class_id)
        .options(selectinload(Quiz.questions))
        .order_by(Quiz.created_at.desc())
        .all()
    )


def add_question(quiz: Quiz, qtype: str, prompt: str, options=None, correct_answer=None, mark=None) -> Question:
    def _add():
        q = Question(
            quiz_id=quiz.id,
            type=qtype,
            prompt=prompt.strip(),
            options=options,
            correct_answer=correct_answer,
            mark=mark,
        )
        db.session.add(q)
        return q

    return tx(_add)


def delete_question(question: Question) -> None:
    def _del():
        db.session.delete(question)

    tx(_del)


def start_attempt(quiz: Quiz, student_id: int) -> tuple[QuizAttempt | None, str | None]:
    """
    محاولة جديدة (مع احترام عدد المحاولات المسموح). يعيد محاولة جارية قائمة إن وجدت.
    P1-05: عند سباق متزامن يفشل الإدخال على القيد الجزئي فنعيد المحاولة القائمة بدل 500.
    """
    in_progress = QuizAttempt.query.filter_by(quiz_id=quiz.id, student_id=student_id, status="in_progress").first()
    if in_progress:
        return in_progress, None
    used = QuizAttempt.query.filter_by(quiz_id=quiz.id, student_id=student_id).count()
    if used >= quiz.attempts_allowed:
        return None, _("استنفدت محاولاتك لهذا الاختبار.")

    def _create():
        attempt = QuizAttempt(
            quiz_id=quiz.id,
            student_id=student_id,
            attempt_no=used + 1,
            status="in_progress",
            started_at=datetime.now(UTC),
        )
        db.session.add(attempt)
        return attempt

    try:
        return tx(_create), None
    except SQLAlchemyError:
        # سباق تزامن: محاولة أخرى أنشأت صفّاً في نفس اللحظة — أعِد الجارية إن وجدت
        existing = QuizAttempt.query.filter_by(quiz_id=quiz.id, student_id=student_id, status="in_progress").first()
        if existing:
            return existing, None
        raise


def deadline_exceeded(attempt: QuizAttempt) -> bool:
    """
    P1-11: هل تجاوزت المحاولة مدة الاختبار المحددة من الخادم؟
    مهلة السماح QUIZ_GRACE_SECONDS (افتراضي 30 ثانية) لتقلبات الشبكة.
    """
    quiz = attempt.quiz
    if not quiz.duration_min or not attempt.started_at:
        return False
    started = attempt.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = datetime.now(UTC) - started
    grace = timedelta(seconds=current_app.config.get("QUIZ_GRACE_SECONDS", 30))
    return elapsed > timedelta(minutes=quiz.duration_min) + grace


def save_answer(attempt: QuizAttempt, question_id: int, answer) -> None:
    """
    يحفظ إجابة سؤال — P1-11: يرفض أي حفظ بعد انتهاء وقت الاختبار من الخادم.
    """
    if attempt.status != "in_progress":
        raise TxError(_("هذه المحاولة مُسلَّمة بالفعل."))
    if deadline_exceeded(attempt):
        raise TxError(_("انتهى وقت الاختبار — لم يُقبل حفظ إجابات جديدة."))

    def _save():
        row = Answer.query.filter_by(attempt_id=attempt.id, question_id=question_id).first()
        if row:
            row.answer = answer
        else:
            db.session.add(Answer(attempt_id=attempt.id, question_id=question_id, answer=answer))

    tx(_save)


def _grade_answer(question: Question, answer) -> tuple[bool | None, float | None]:
    """تصحيح آلي للأوتوماتيكي؛ المقالي يرجع None للتصحيح اليدوي."""
    if question.type == "mcq":
        correct = (question.correct_answer or {}).get("index")
        given = (answer or {}).get("index")
        if correct is None or given is None:
            return None, None
        ok = int(correct) == int(given)
        return ok, (question.mark if ok else 0)
    if question.type == "true_false":
        correct = (question.correct_answer or {}).get("value")
        given = (answer or {}).get("value")
        if correct is None or given is None:
            return None, None
        ok = bool(correct) == bool(given)
        return ok, (question.mark if ok else 0)
    return None, None  # essay/matching — تصحيح يدوي


def submit_attempt(attempt: QuizAttempt, *, allow_after_deadline: bool = False) -> float:
    """
    يُنهي المحاولة: تصحيح آلي + حساب الدرجة الكلية. يعيد الدرجة.
    P1-06: قفل صف المحاولة (FOR UPDATE) لمنع تسليم مزدوج متزامن.
    P2-14: جلب كل الإجابات دفعة واحدة بدل استعلام لكل سؤال (N+1).
    P1-11: يرفض التسليم اليدوي بعد انتهاء الوقت إلا مع allow_after_deadline
    (التصحيح التلقائي عند نفاد الوقت أو المراقبة proctoring).
    """
    total = Decimal("0")

    def _submit():
        nonlocal total
        locked = db.session.execute(
            select(QuizAttempt).where(QuizAttempt.id == attempt.id).with_for_update()
        ).scalar_one()
        if locked.status != "in_progress":
            raise TxError(_("تم تسليم هذه المحاولة مسبقاً."))
        if not allow_after_deadline and deadline_exceeded(locked):
            raise TxError(_("انتهى وقت الاختبار."))

        questions = locked.quiz.questions
        # P2-14: استعلام واحد بدل N+1
        answers = {
            a.question_id: a
            for a in Answer.query.filter(
                Answer.attempt_id == locked.id,
                Answer.question_id.in_([q.id for q in questions] or [0]),
            ).all()
        }
        for question in questions:
            answer = answers.get(question.id)
            if answer is None:
                answer = Answer(attempt_id=locked.id, question_id=question.id, answer=None)
                db.session.add(answer)
            if answer.answer is not None:
                is_correct, mark = _grade_answer(question, answer.answer)
                answer.is_correct = is_correct
                answer.awarded_mark = mark
                if mark:
                    total += Decimal(str(mark))
        locked.status = "submitted"
        locked.submitted_at = db.func.now()
        locked.score = float(total.quantize(Decimal("0.01")))

    try:
        tx(_submit)
    except TxError:
        db.session.rollback()
        raise
    return float(total.quantize(Decimal("0.01")))


def grade_essay(answer: Answer, awarded_mark: float | None) -> None:
    def _grade():
        answer.awarded_mark = awarded_mark
        answer.is_correct = awarded_mark is not None and awarded_mark > 0
        # تحديث درجة المحاولة بعد التصحيح اليدوي
        attempt = answer.attempt
        total = 0.0
        for a in attempt.answers:
            if a.awarded_mark is not None:
                total += float(a.awarded_mark)
        attempt.score = round(total, 2)

    tx(_grade)


def get_attempt(attempt_id: int) -> QuizAttempt | None:
    return db.session.execute(
        db.select(QuizAttempt)
        .options(
            joinedload(QuizAttempt.quiz).selectinload(Quiz.questions),
            selectinload(QuizAttempt.answers),
        )
        .where(QuizAttempt.id == attempt_id)
    ).scalar_one_or_none()
