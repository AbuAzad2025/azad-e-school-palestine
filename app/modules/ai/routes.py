"""مسارات API للذكاء الاصطناعي — Streaming SSE endpoints"""

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
def suggest_grade():
    """اقتراح درجة للواجب (للمعلمين)."""
    data = request.get_json() or {}
    student_answer = data.get("student_answer", "")
    question_type = data.get("question_type", "essay")
    correct_answer = data.get("correct_answer")
    rubric = data.get("rubric")

    if not student_answer:
        return jsonify({"error": _("إجابة الطالب مطلوبة")}), 400

    # Check permission - only teachers can grade
    from app.models.user import UserRole

    if current_user.role not in (UserRole.teacher, UserRole.school_admin, UserRole.super_admin):
        return jsonify({"error": _("غير مسموح")}), 403

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
def generate_questions():
    """توليد أسئلة امتحان (للمعلمين)."""
    data = request.get_json() or {}
    topic = data.get("topic", "")
    count = min(max(data.get("count", 5), 1), 20)
    question_types = data.get("question_types", ["mcq", "true_false", "essay"])
    difficulty = data.get("difficulty", "medium")

    if not topic:
        return jsonify({"error": _("الموضوع مطلوب")}), 400

    # Check permission - only teachers
    from app.models.user import UserRole

    if current_user.role not in (UserRole.teacher, UserRole.school_admin, UserRole.super_admin):
        return jsonify({"error": _("غير مسموح")}), 403

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
def usage_stats():
    """إحصائيات استخدام AI."""
    from app.models.user import UserRole

    if current_user.role not in (UserRole.school_admin, UserRole.super_admin):
        return jsonify({"error": _("غير مسموح")}), 403

    ai_service = get_ai_service()
    days = request.args.get("days", 30, type=int)
    stats = ai_service.get_usage_stats(days=days)
    return jsonify(stats)
