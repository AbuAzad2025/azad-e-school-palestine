"""مسارات التقييم: قائمة اختبارات، إنشاء، محاولة، نتائج، تصحيح مقالي."""

from app.core.db import TxError, tx
from app.core.permissions import class_access_required, class_teach_required, role_required
from app.extensions import db
from app.models.assessment import Answer, ProctoringLog, Question, Quiz, QuizAttempt
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
from app.services.question_bank import (
    create_bank_question,
    delete_bank_question,
    import_to_quiz,
    list_bank_questions,
)
from app.services.quiz_stats import get_quiz_stats
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload

from . import bp
from .forms import QuestionForm, QuizForm


def _class_or_404(class_id):
    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    return class_room


@bp.get("/<int:class_id>/quizzes")
@class_access_required
def quiz_list(class_id, class_room=None):
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
@class_teach_required
def quiz_new(class_id, class_room=None):
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
@class_teach_required
def quiz_manage(class_id, quiz_id, class_room=None):
    quiz = Quiz.query.options(selectinload(Quiz.questions)).get_or_404(quiz_id)
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
    if attempt is None:
        flash(_("حدث خطأ أثناء إنشاء المحاولة."), "danger")
        return redirect(url_for("assessment.quiz_list", class_id=quiz.class_id))
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
    timed_out = False
    for question in attempt.quiz.questions:
        value = request.form.get(f"q_{question.id}")
        if value is None:
            continue
        try:
            save_answer(attempt, question.id, _parse_answer(question, value))
        except TxError as exc:
            # P1-11: رفض الحفظ بعد انتهاء وقت الاختبار من الخادم
            flash(_(str(exc)), "warning")
            timed_out = True
            break
    if not timed_out:
        flash(_("حُفظت إجاباتك."), "info")
    return redirect(url_for("assessment.attempt_do", attempt_id=attempt.id))


@bp.post("/attempt/<int:attempt_id>/submit")
@login_required
def attempt_submit(attempt_id):
    from app.services.email import send_quiz_result_email

    attempt = get_attempt(attempt_id)
    if not attempt or attempt.student_id != current_user.id:
        abort(403)

    def _notify_and_email(score: float) -> None:
        if attempt.quiz.created_by is not None:
            notify(
                attempt.quiz.created_by,
                "result",
                _("محاولة جديدة في اختبار"),
                f"{current_user.name_ar}: {score}",
            )
        send_quiz_result_email(current_user, attempt.quiz, score)

    if attempt.status != "in_progress":
        return redirect(url_for("assessment.attempt_result", attempt_id=attempt.id))
    # P1-11: حفظ الإجابات الواردة قبل انتهاء الوقت فقط، ثم تصحيح ما حُفظ
    for question in attempt.quiz.questions:
        value = request.form.get(f"q_{question.id}")
        if value is not None:
            try:
                save_answer(attempt, question.id, _parse_answer(question, value))
            except TxError:
                break  # الوقت انتهى — نسلّم الإجابات المحفوظة فقط
    try:
        score = submit_attempt(attempt)
    except TxError as exc:
        if "مسبقاً" in str(exc):
            return redirect(url_for("assessment.attempt_result", attempt_id=attempt.id))
        # انتهى الوقت: تصحيح تلقائي للإجابات المحفوظة دون إجابات جديدة
        score = submit_attempt(attempt, allow_after_deadline=True)
        flash(_("انتهى وقت الاختبار — صُحّحت الإجابات المحفوظة."), "warning")
        audit("quiz.submit", "quiz_attempts", attempt.id, {"score": score})
        _notify_and_email(score)
        return redirect(url_for("assessment.attempt_result", attempt_id=attempt.id))
    audit("quiz.submit", "quiz_attempts", attempt.id, {"score": score})
    _notify_and_email(score)
    flash(_("سُلّم اختبارك."), "success")
    return redirect(url_for("assessment.attempt_result", attempt_id=attempt.id))


def _parse_answer(question, raw: str):
    if question.type == "true_false":
        return {"value": raw == "true"}
    if question.type == "mcq":
        # P2-12: مدخل معدوم → 400 بدل انفجار ValueError كـ500
        try:
            index = int(raw)
        except (TypeError, ValueError):
            abort(400)
        return {"index": index}
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
    attempts = (
        QuizAttempt.query.filter_by(quiz_id=quiz_id)
        .options(selectinload(QuizAttempt.answers), joinedload(QuizAttempt.student))
        .order_by(QuizAttempt.score.desc())
        .all()
    )
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


# ═══════════════════════════════════════════════════════════════════════
# بنك الأسئلة
# ═══════════════════════════════════════════════════════════════════════


@bp.get("/question-bank")
@login_required
@role_required(UserRole.teacher, UserRole.school_admin)
def question_bank_list():
    from app.models.school import Subject

    subjects = Subject.query.order_by(Subject.name_ar).all()
    questions = list_bank_questions(
        current_user.id,
        subject_id=request.args.get("subject_id", type=int),
        question_type=request.args.get("type"),
        difficulty=request.args.get("difficulty", type=int),
    )
    return render_template(
        "assessment/question_bank.html",
        questions=questions,
        subjects=subjects,
    )


@bp.post("/question-bank/new")
@login_required
@role_required(UserRole.teacher, UserRole.school_admin)
def question_bank_create():
    question_text = request.form.get("question_text", "").strip()
    question_type = request.form.get("question_type", "mcq")
    subject_id = request.form.get("subject_id", type=int)
    difficulty = request.form.get("difficulty", 3, type=int)
    is_shared = request.form.get("is_shared") == "on"

    options = None
    correct_answer = None
    if question_type == "mcq":
        opts = []
        for label, key in [("أ", "option_a"), ("ب", "option_b"), ("ج", "option_c"), ("د", "option_d")]:
            val = request.form.get(key, "").strip()
            if val:
                opts.append({"label": label, "text": val})
        if opts:
            options = {"items": opts}
        correct_index = request.form.get("correct_index", type=int)
        if correct_index is not None:
            correct_answer = {"index": correct_index}
    elif question_type == "true_false":
        correct_answer = {"value": request.form.get("correct_tf") == "true"}

    bq, error = create_bank_question(
        teacher_id=current_user.id,
        school_id=current_user.school_id or 0,
        question_text=question_text,
        question_type=question_type,
        subject_id=subject_id,
        options=options,
        correct_answer=correct_answer,
        difficulty=difficulty,
        is_shared=is_shared,
    )
    if error:
        flash(_(error), "danger")
    else:
        flash(_("أُضيف السؤال إلى البنك."), "success")
    return redirect(url_for("assessment.question_bank_list"))


@bp.post("/question-bank/<int:question_id>/delete")
@login_required
@role_required(UserRole.teacher, UserRole.school_admin)
def question_bank_delete(question_id):
    ok, error = delete_bank_question(question_id, current_user.id)
    if error:
        flash(_(error), "danger")
    else:
        flash(_("حُذف السؤال من البنك."), "success")
    return redirect(url_for("assessment.question_bank_list"))


@bp.get("/quiz/<int:quiz_id>/bank-import")
@login_required
def bank_import_page(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    class_room = _class_or_404(quiz.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    questions = list_bank_questions(current_user.id)
    return render_template(
        "assessment/bank_import.html",
        class_room=class_room,
        quiz=quiz,
        questions=questions,
    )


@bp.post("/quiz/<int:quiz_id>/bank-import")
@login_required
def bank_import_action(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    class_room = _class_or_404(quiz.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    selected = request.form.getlist("question_ids")
    question_ids = [int(qid) for qid in selected if qid.isdigit()]
    count, error = import_to_quiz(quiz, question_ids, current_user.id)
    if error:
        flash(_(error), "danger")
    else:
        flash(_("تم استيراد %(count)d أسئلة.", count=count), "success")
    return redirect(url_for("assessment.quiz_manage", class_id=class_room.id, quiz_id=quiz.id))


# ═══════════════════════════════════════════════════════════════════════
# مراقبة الاختبارات (Proctoring)
# ═══════════════════════════════════════════════════════════════════════


@bp.post("/attempt/<int:attempt_id>/proctor")
@login_required
def proctor_log(attempt_id):
    attempt = get_attempt(attempt_id)
    if not attempt or attempt.student_id != current_user.id:
        return jsonify({"error": "forbidden"}), 403
    event_type = request.json.get("event_type") if request.is_json else None
    if event_type not in ("tab_switch", "fullscreen_exit", "auto_submit"):
        return jsonify({"error": "invalid event_type"}), 400

    def _log():
        db.session.add(ProctoringLog(attempt_id=attempt_id, event_type=event_type))

    tx(_log)

    quiz = attempt.quiz

    def _force_submit(reason: str):
        """تصحيح تلقائي (مراقبة): يُسمح بعد المهلة، والإجابات المتأخرة تُهمل بأمان."""
        try:
            for q in quiz.questions:
                value = request.json.get(f"q_{q.id}") if request.is_json else None
                if value is not None:
                    try:
                        save_answer(attempt, q.id, _parse_answer(q, value))
                    except TxError:
                        break
            submit_attempt(attempt, allow_after_deadline=True)
        except Exception:
            pass
        return jsonify({"auto_submit": True, "reason": reason})

    if event_type == "tab_switch":
        tab_count = ProctoringLog.query.filter_by(
            attempt_id=attempt_id,
            event_type="tab_switch",
        ).count()
        if tab_count >= quiz.max_tab_switches:
            if attempt.status == "in_progress":
                return _force_submit("tab_switches_exceeded")
    elif event_type == "fullscreen_exit" and quiz.fullscreen_required:
        exit_count = ProctoringLog.query.filter_by(
            attempt_id=attempt_id,
            event_type="fullscreen_exit",
        ).count()
        if exit_count >= 2:
            if attempt.status == "in_progress":
                return _force_submit("fullscreen_exit_exceeded")

    return jsonify({"ok": True, "event_type": event_type})


@bp.get("/quiz/<int:quiz_id>/stats")
@login_required
@role_required(UserRole.teacher, UserRole.school_admin)
def quiz_stats(quiz_id):
    from app.models.assessment import Quiz

    quiz = Quiz.query.get_or_404(quiz_id)
    class_room = ClassRoom.query.get_or_404(quiz.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)

    stats = get_quiz_stats(quiz_id)
    if not stats:
        flash(_("لا توجد بيانات إحصائية لهذا الاختبار."), "info")
        return redirect(url_for("assessment.quiz_results", quiz_id=quiz_id))

    return render_template("assessment/quiz_stats.html", quiz=quiz, stats=stats, class_room=class_room)
