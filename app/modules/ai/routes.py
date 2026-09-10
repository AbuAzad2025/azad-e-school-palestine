"""مسارات API للذكاء الاصطناعي — Streaming SSE endpoints"""

from app.core.permissions import require_ai_quota, role_required
from app.extensions import db
from app.models.user import UserRole
from app.services.ai import get_ai_service
from flask import Response, jsonify, render_template, request, stream_with_context
from flask_babel import _
from flask_login import current_user, login_required

from . import bp


@bp.get("/chat")
@login_required
def chat_page():
    """صفحة المحادثة مع المساعد الذكي."""
    from app.models.ai import AiSession
    from sqlalchemy.orm import selectinload

    # Load user's chat sessions
    sessions_data = []
    for s in (
        AiSession.query.filter_by(user_id=current_user.id, session_type="student_helper")
        .options(selectinload(AiSession.messages))
        .order_by(AiSession.created_at.desc())
        .all()
    ):
        sessions_data.append(
            {
                "id": s.id,
                "model": s.meta.get("model") if s.meta else "gpt-4o-mini",
                "messages": [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in s.messages],
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
        )

    return render_template("ai/chat.html", chat_sessions=sessions_data, messages=[])


@bp.post("/chat/stream")
@login_required
@require_ai_quota
def chat_stream():
    """SSE endpoint for streaming AI chat responses."""
    data = request.get_json() or {}
    question = data.get("question", "").strip()
    context = data.get("context")
    class_id = data.get("class_id")
    lesson_id = data.get("lesson_id")

    if not question:
        return jsonify({"error": _("السؤال مطلوب")}), 400

    ai_service = get_ai_service()

    def generate():
        import asyncio

        async def stream():
            async for chunk in ai_service.ask_question_stream(
                user_id=current_user.id, question=question, context=context, class_id=class_id, lesson_id=lesson_id
            ):
                yield chunk

        # Run async generator in sync context
        loop = asyncio.new_event_loop()
        try:
            async_gen = stream()
            while True:
                try:
                    chunk = loop.run_until_complete(async_gen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp.post("/chat")
@login_required
@require_ai_quota
def chat():
    """Non-streaming chat endpoint."""
    data = request.get_json() or {}
    question = data.get("question", "").strip()
    context = data.get("context")
    class_id = data.get("class_id")
    lesson_id = data.get("lesson_id")

    if not question:
        return jsonify({"error": _("السؤال مطلوب")}), 400

    ai_service = get_ai_service()
    import asyncio

    result = asyncio.run(
        ai_service.ask_question(
            user_id=current_user.id, question=question, context=context, class_id=class_id, lesson_id=lesson_id
        )
    )
    return jsonify(result)


@bp.post("/grade/suggest")
@login_required
@require_ai_quota
@role_required(UserRole.teacher, UserRole.school_admin)
def suggest_grade():
    """اقتراح درجة للواجب (للمعلمين)."""
    data = request.get_json() or {}
    student_answer = data.get("student_answer", "")
    question_type = data.get("question_type", "essay")
    correct_answer = data.get("correct_answer")
    rubric = data.get("rubric")

    if not student_answer:
        return jsonify({"error": _("إجابة الطالب مطلوبة")}), 400

    ai_service = get_ai_service()
    import asyncio

    result = asyncio.run(
        ai_service.suggest_grade(
            student_answer=student_answer,
            question_type=question_type,
            correct_answer=correct_answer,
            rubric=rubric,
            user_id=current_user.id,
        )
    )
    return jsonify(result)


@bp.post("/questions/generate")
@login_required
@require_ai_quota
@role_required(UserRole.teacher, UserRole.school_admin)
def generate_questions():
    """توليد أسئلة امتحان (للمعلمين)."""
    data = request.get_json() or {}
    topic = data.get("topic", "")
    count = min(max(data.get("count", 5), 1), 20)
    question_types = data.get("question_types", ["mcq", "true_false", "essay"])
    difficulty = data.get("difficulty", "medium")

    if not topic:
        return jsonify({"error": _("الموضوع مطلوب")}), 400

    ai_service = get_ai_service()
    import asyncio

    questions = asyncio.run(
        ai_service.generate_questions(
            topic=topic, count=count, question_types=question_types, difficulty=difficulty, user_id=current_user.id
        )
    )
    return jsonify({"questions": questions})


@bp.get("/usage/stats")
@login_required
@role_required(UserRole.school_admin)
def usage_stats():
    """إحصائيات استخدام AI."""
    ai_service = get_ai_service()
    days = request.args.get("days", 30, type=int)
    stats = ai_service.get_usage_stats(days=days)
    return jsonify(stats)


# ═══════════════════════════════════════════════════════════════════════════
# RAG Tutor — استرجاع مقيّد بالمدرسة مع اقتباسات موثوقة (P2-RAG-HTTP)
# ═══════════════════════════════════════════════════════════════════════════


@bp.post("/rag/query")
@login_required
@require_ai_quota
def rag_query():
    """استعلام المعلم الافتراضي المقيّد بمحتوى مدرسة المستخدم.

    Body: {"question": string}
    Returns 200: {answer, sources[], confidence, method}
            400: سؤال فارغ · 403: حصة AI (AI_QUOTA_EXCEEDED / AI_DISABLED_FOR_TENANT)
    """
    from app.core.tenancy import current_school_id
    from app.services.rag_service import query_school_rag_tutor

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": {"message": _("السؤال مطلوب"), "code": "VALIDATION_ERROR"}}), 400

    school_id = current_school_id()
    if school_id is None:
        # super_admin أو مستخدم فردي — بلا نطاق مدرسة لا يوجد محتوى RAG
        return jsonify(
            {
                "error": {
                    "message": _("لا تنتمي لمدرسة؛ استعلام RAG يتطلب نطاق مدرسة."),
                    "code": "AI_DISABLED_FOR_TENANT",
                }
            }
        ), 403

    result, err = query_school_rag_tutor(school_id, current_user.id, question)
    if err or result is None:
        return jsonify({"error": {"message": err or _("فشل الاستعلام"), "code": "RAG_QUERY_FAILED"}}), 502
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# Quiz Generation from Lesson — مسودة دائماً، موافقة بشرية قبل النشر
# ═══════════════════════════════════════════════════════════════════════════


@bp.post("/quiz/generate")
@login_required
@require_ai_quota
@role_required(UserRole.teacher, UserRole.school_admin)
def generate_quiz():
    """توليد اختبار من درس عبر AI — يُحفظ كمسودة (status=draft).

    Body: {"lesson_id": int, "question_count": 1-20, "difficulty": easy|medium|hard}
    Returns 201: {quiz_id, title, question_count, status: "draft"}
            400/403/404/502 per pipeline error.
    """
    from app.services.quiz_ai_service import generate_quiz_from_lesson

    data = request.get_json(silent=True) or {}
    lesson_id = data.get("lesson_id")
    if not lesson_id:
        return jsonify({"error": {"message": _("معرّف الدرس مطلوب"), "code": "VALIDATION_ERROR"}}), 400

    question_count = min(max(int(data.get("question_count", 5) or 5), 1), 20)
    difficulty = data.get("difficulty", "medium")
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"

    # تحقق ملكية الدرس: يجب أن يقع داخل نطاق مدرسة المستخدم (لا عزل = لا مساس)
    from app.core.tenancy import current_school_id
    from app.models.content import Lesson

    school_id = current_school_id()
    lesson = db.session.get(Lesson, lesson_id)
    if lesson is None:
        return jsonify({"error": {"message": _("الدرس غير موجود"), "code": "NOT_FOUND"}}), 404
    lesson_class = lesson.class_room
    if lesson_class is None or school_id is None or lesson_class.school_id != school_id:
        return jsonify({"error": {"message": _("الدرس خارج نطاق مدرستك"), "code": "FORBIDDEN"}}), 403

    quiz, err = generate_quiz_from_lesson(
        lesson_id=lesson_id,
        question_count=question_count,
        difficulty=difficulty,
        created_by=current_user.id,
    )
    if quiz is None:
        return jsonify({"error": {"message": err or _("فشل التوليد"), "code": "QUIZ_GENERATION_FAILED"}}), 502

    return jsonify(
        {
            "quiz_id": quiz.id,
            "title": quiz.title,
            "question_count": len(quiz.questions),
            "status": quiz.status,
        }
    ), 201
    """إحصائيات استخدام AI."""
    ai_service = get_ai_service()
    days = request.args.get("days", 30, type=int)
    stats = ai_service.get_usage_stats(days=days)
    return jsonify(stats)
