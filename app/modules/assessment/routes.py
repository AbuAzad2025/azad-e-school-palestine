"""مسارات التقييم: قائمة اختبارات، إنشاء، محاولة، نتائج، تصحيح مقالي."""

from app.models.assessment import Answer, Question, Quiz, QuizAttempt
from app.models.class_room import ClassRoom
from app.models.user import UserRole
from app.services.access import can_teach_class, can_view_class
from app.services.ai import get_ai_service
from app.services.assessment import (
    add_question,
    create_quiz,
    delete_question,
    get_attempt,
    grade_essay,
    list_quizzes,
    save_answer,
    start_attempt,
    submit_attempt,
)
from app.services.communication import audit, notify
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import QuestionForm, QuizForm


def _class_or_404(class_id):
    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    return class_room


@bp.get("/<int:class_id>/quizzes")
@login_required
def quiz_list(class_id):
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    quizzes = list_quizzes(class_id)
    attempts = {}
    if current_user.role == UserRole.student:
        attempts = {
            a.quiz_id: a
            for a in QuizAttempt.query.filter_by(student_id=current_user.id)
            .filter(QuizAttempt.quiz_id.in_([q.id for q in quizzes] or [0]))
            .all()
        }
    return render_template(
        "assessment/quiz_list.html",
        class_room=class_room,
        quizzes=quizzes,
        attempts=attempts,
        can_teach=can_teach_class(class_room, current_user),
    )


@bp.route("/<int:class_id>/quizzes/new", methods=["GET", "POST"])
@login_required
def quiz_new(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    form = QuizForm()
    if form.validate_on_submit():
        quiz, error = create_quiz(
            class_id=class_id,
            title=form.title.data,
            duration_min=form.duration_min.data,
            attempts_allowed=form.attempts_allowed.data,
            shuffle=form.shuffle.data,
            show_answers_after=form.show_answers_after.data,
            created_by=current_user.id,
        )
        if error:
            flash(_(error), "danger")
        elif quiz is not None:
            audit("quiz.create", "quizzes", quiz.id)
            flash(_("تم إنشاء الاختبار. أضف الأسئلة الآن."), "success")
            return redirect(url_for("assessment.quiz_manage", class_id=class_id, quiz_id=quiz.id))
    return render_template("content/lesson_form.html", class_room=class_room, form=form, lesson=None)


@bp.route("/quiz/generate-ai", methods=["POST"])
@login_required
def ai_generate_questions():
    if not get_ai_service()._verify_permission(current_user, UserRole.teacher):
        abort(403)
    data = request.get_json()
    topic = data.get("topic", "")
    count = min(max(data.get("count", 5), 1), 10)
    question_types = data.get("question_types", ["mcq", "true_false", "essay"])
    difficulty = data.get("difficulty", "medium")

    questions = get_ai_service().generate_questions(
        topic=topic, count=count, question_types=question_types, difficulty=difficulty
    )
    return {"questions": questions}, 200


@bp.route("/<int:class_id>/quizzes/<int:quiz_id>", methods=["GET", "POST"])
@login_required
def quiz_manage(class_id, quiz_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.class_id != class_id:
        abort(404)
    form = QuestionForm()
    if form.validate_on_submit():
        if form.qtype.data == "true_false":
            options = None
            correct = {"value": form.correct_tf.data == "true"}
        elif form.qtype.data == "essay":
            options = None
            correct = None
        else:
            options = {
                "items": [
                    {"label": "أ", "text": form.option_a.data},
                    {"label": "ب", "text": form.option_b.data},
                    {"label": "ج", "text": form.option_c.data},
                    {"label": "د", "text": form.option_d.data},
                ]
            }
            correct = {"index": int(form.correct_index.data)}
        add_question(
            quiz, form.qtype.data, form.prompt.data, options=options, correct_answer=correct, mark=form.mark.data
        )
        flash(_("أُضيف السؤال."), "success")
        return redirect(url_for("assessment.quiz_manage", class_id=class_id, quiz_id=quiz.id))
    return render_template("assessment/quiz_manage.html", class_room=class_room, quiz=quiz, form=form)


@bp.post("/questions/<int:question_id>/delete")
@login_required
def question_delete(question_id):
    question = Question.query.get_or_404(question_id)
    class_room = _class_or_404(question.quiz.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    delete_question(question)
    flash(_("حُذف السؤال."), "success")
    return redirect(url_for("assessment.quiz_manage", class_id=class_room.id, quiz_id=question.quiz_id))


@bp.get("/quizzes/<int:quiz_id>/attempt")
@login_required
def attempt_start(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    class_room = _class_or_404(quiz.class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if current_user.role != UserRole.student:
        flash(_("المحاولة للطلاب فقط."), "warning")
        return redirect(url_for("assessment.quiz_list", class_id=quiz.class_id))
    attempt, error = start_attempt(quiz, current_user.id)
    if error:
        flash(_(error), "danger")
        return redirect(url_for("assessment.quiz_list", class_id=quiz.class_id))
    assert attempt is not None
    return redirect(url_for("assessment.attempt_do", attempt_id=attempt.id))


@bp.get("/attempt/<int:attempt_id>")
@login_required
def attempt_do(attempt_id):
    attempt = get_attempt(attempt_id)
    if not attempt or attempt.student_id != current_user.id:
        abort(403)
    quiz = attempt.quiz
    if attempt.status != "in_progress":
        return redirect(url_for("assessment.attempt_result", attempt_id=attempt.id))
    class_room = _class_or_404(quiz.class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    answers = {a.question_id: a for a in attempt.answers}
    return render_template("assessment/attempt.html", attempt=attempt, quiz=quiz, answers=answers)


@bp.post("/attempt/<int:attempt_id>/save")
@login_required
def attempt_save(attempt_id):
    attempt = get_attempt(attempt_id)
    if not attempt or attempt.student_id != current_user.id:
        abort(403)
    for question in attempt.quiz.questions:
        value = request.form.get(f"q_{question.id}")
        if value is None:
            continue
        answer = _parse_answer(question, value)
        save_answer(attempt, question.id, answer)
    flash(_("حُفظت إجاباتك."), "info")
    return redirect(url_for("assessment.attempt_do", attempt_id=attempt.id))


@bp.post("/attempt/<int:attempt_id>/submit")
@login_required
def attempt_submit(attempt_id):
    attempt = get_attempt(attempt_id)
    if not attempt or attempt.student_id != current_user.id:
        abort(403)
    if attempt.status != "in_progress":
        return redirect(url_for("assessment.attempt_result", attempt_id=attempt.id))
    for question in attempt.quiz.questions:
        value = request.form.get(f"q_{question.id}")
        if value is not None:
            save_answer(attempt, question.id, _parse_answer(question, value))
    score = submit_attempt(attempt)
    audit("quiz.submit", "quiz_attempts", attempt.id, {"score": score})
    if attempt.quiz.created_by is not None:
        notify(
            attempt.quiz.created_by,
            "result",
            _("محاولة جديدة في اختبار"),
            f"{current_user.name_ar}: {score}",
        )
    flash(_("سُلّم اختبارك."), "success")
    return redirect(url_for("assessment.attempt_result", attempt_id=attempt.id))


def _parse_answer(question, raw: str):
    if question.type == "true_false":
        return {"value": raw == "true"}
    if question.type == "mcq":
        return {"index": int(raw)}
    return {"text": raw}  # مقالي


@bp.get("/attempt/<int:attempt_id>/result")
@login_required
def attempt_result(attempt_id):
    attempt = get_attempt(attempt_id)
    if not attempt:
        abort(404)
    class_room = _class_or_404(attempt.quiz.class_id)
    is_owner = attempt.student_id == current_user.id
    is_teacher = can_teach_class(class_room, current_user)
    if not (is_owner or is_teacher):
        abort(403)
    answers = {a.question_id: a for a in attempt.answers}
    return render_template(
        "assessment/attempt_result.html",
        attempt=attempt,
        quiz=attempt.quiz,
        answers=answers,
        is_teacher=is_teacher,
    )


@bp.get("/quizzes/<int:quiz_id>/results")
@login_required
def quiz_results(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    class_room = _class_or_404(quiz.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    attempts = QuizAttempt.query.filter_by(quiz_id=quiz_id).order_by(QuizAttempt.score.desc()).all()
    pending = [a for a in attempts if any(x.is_correct is None and x.answer is not None for x in a.answers)]
    return render_template(
        "assessment/quiz_results.html",
        class_room=class_room,
        quiz=quiz,
        attempts=attempts,
        pending=pending,
    )


@bp.post("/answers/<int:answer_id>/grade")
@login_required
def answer_grade(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    class_room = _class_or_404(answer.attempt.quiz.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    mark = request.form.get("mark", type=float)
    grade_essay(answer, mark)
    flash(_("حُدّثت درجة السؤال المقالي."), "success")
    return redirect(url_for("assessment.attempt_result", attempt_id=answer.attempt_id))
