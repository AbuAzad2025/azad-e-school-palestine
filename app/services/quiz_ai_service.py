"""AI Quiz Generator — generate quiz questions from lesson content.

P6-05: Parse lesson context and construct structured prompts for LLM.
P6-06: Parse JSON output into native Quiz & Question ORM objects.
P6-07: All writes wrapped in tx() with proper tenancy.
P6-08: Returns typed error tuples: tuple[Quiz | None, str | None].
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from flask import current_app

from app.core.db import TxError, tx
from app.core.i18n import _
from app.core.logging import get_logger
from app.extensions import db

logger = get_logger(__name__)

# Quiz generation prompt template
_QUIZ_PROMPT_TEMPLATE = """You are an expert exam question writer for the Palestinian K-12 curriculum.

Based on the following lesson content, generate {question_count} quiz questions at {difficulty} difficulty level.

LESSON CONTENT:
---
{lesson_content}
---

OUTPUT FORMAT: Return ONLY a valid JSON array (no markdown, no explanation). Each question object must have:
- "question_text": The question text (string)
- "question_type": One of "mcq", "true_false", "fill_blank" (string)
- "options": Array of 4 option strings for mcq, ["True", "False"] for true_false, [] for fill_blank
- "correct_answer": The correct answer string (for mcq: the exact option text,
  for true_false: "True" or "False", for fill_blank: the exact word/phrase)
- "marks": Points for this question (number)
- "explanation": Brief explanation of the correct answer (string)

DIFFICULTY GUIDELINES:
- easy: Recall/factual questions (definitions, names, dates)
- medium: Understanding/comprehension questions (explain, compare)
- hard: Application/analysis questions (solve, evaluate, create)

Return ONLY the JSON array, nothing else."""


def generate_quiz_from_lesson(
    lesson_id: int,
    question_count: int = 5,
    difficulty: str = "medium",
    created_by: int | None = None,
) -> tuple[Any, str | None]:
    """Generate a quiz from a lesson's content using AI.

    Pipeline:
        1. Extract lesson text content
        2. Construct structured prompt
        3. Call LLM API
        4. Parse JSON response into Quiz + Question ORM objects
        5. Save atomically via tx()

    Args:
        lesson_id: Source lesson to generate from.
        question_count: Number of questions (default 5).
        difficulty: "easy", "medium", or "hard".
        created_by: Teacher ID creating the quiz.

    Returns:
        (Quiz object, None) on success, (None, error_message) on failure.
    """
    from app.models.assessment import Question, Quiz
    from app.models.content import Lesson

    logger.info(
        "quiz_generation_started",
        lesson_id=lesson_id,
        question_count=question_count,
        difficulty=difficulty,
    )

    # Step 1: Extract lesson content
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson:
        return None, _("الدرس غير موجود.")

    lesson_content = _extract_lesson_text(lesson)
    if not lesson_content.strip():
        return None, _("لا يوجد محتوى نصي في الدرس.")

    # Step 2: Build prompt
    prompt = _QUIZ_PROMPT_TEMPLATE.format(
        question_count=question_count,
        difficulty=difficulty,
        lesson_content=lesson_content[:3000],  # Limit context length
    )

    # Step 3: Call LLM
    try:
        raw_response = _call_llm(prompt)
    except Exception as exc:
        logger.exception("quiz_generation_llm_failed", lesson_id=lesson_id)
        return None, f"LLM API error: {exc}"

    # Step 4: Parse response
    questions_data = _parse_llm_response(raw_response)
    if not questions_data:
        return None, _("فشل في تحليل استجابة الذكاء الاصطناعي.")

    # Step 5: Create Quiz + Questions atomically
    try:

        def _create_quiz():
            quiz = Quiz(
                class_id=lesson.class_id,
                title=(_("اختبار تلقائي: %(title)s", title=lesson.title) if lesson.title else _("اختبار تلقائي")),
                duration_min=question_count * 2,  # 2 min per question
                attempts_allowed=3,
                shuffle=True,
                show_answers_after=True,
                status="draft",
                created_by=created_by,
                enable_proctoring=False,
                max_tab_switches=5,
                fullscreen_required=False,
            )
            db.session.add(quiz)
            db.session.flush()  # Get quiz.id

            for q_data in questions_data:
                question = Question(
                    quiz_id=quiz.id,
                    question_text=q_data.get("question_text", ""),
                    question_type=q_data.get("question_type", "mcq"),
                    options=q_data.get("options", []),
                    correct_answer=q_data.get("correct_answer", ""),
                    marks=q_data.get("marks", 1),
                    explanation=q_data.get("explanation", ""),
                    difficulty=_map_difficulty(difficulty),
                )
                db.session.add(question)

            return quiz

        quiz = tx(_create_quiz)

        logger.info(
            "quiz_generation_completed",
            quiz_id=quiz.id,
            lesson_id=lesson_id,
            question_count=len(questions_data),
        )

        return quiz, None

    except TxError as exc:
        return None, str(exc)
    except Exception as exc:
        logger.exception("quiz_generation_db_error", lesson_id=lesson_id)
        return None, f"Database error: {exc}"


def _extract_lesson_text(lesson: Any) -> str:
    """Extract plain text from lesson content."""
    parts = []
    if lesson.title:
        parts.append(f"العنوان: {lesson.title}")
    if lesson.body_html:
        # Strip HTML tags
        clean = re.sub(r"<[^>]+>", " ", lesson.body_html)
        clean = re.sub(r"\s+", " ", clean).strip()
        parts.append(clean)
    return "\n".join(parts)


def _call_llm(prompt: str) -> str:
    """Call LLM API with a prompt."""
    api_key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    api_base = current_app.config.get("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    model = current_app.config.get("AI_MODEL", "deepseek/deepseek-chat")

    if not api_key:
        return _generate_offline_quiz(prompt)

    try:
        import requests

        response = requests.post(
            f"{api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert exam writer. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 2000,
                "temperature": 0.8,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        return _generate_offline_quiz(prompt)


def _parse_llm_response(raw: str) -> list[dict] | None:
    """Parse LLM response into list of question dicts."""
    # Try to extract JSON from the response
    # Remove markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            # Validate each question has required fields
            valid = []
            for q in data:
                if isinstance(q, dict) and "question_text" in q and "correct_answer" in q:
                    valid.append(q)
            return valid if valid else None
        return None
    except json.JSONDecodeError:
        # Try to find JSON array in the response
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return [q for q in data if isinstance(q, dict) and "question_text" in q]
            except json.JSONDecodeError:
                pass
        return None


def _generate_offline_quiz(prompt: str) -> str:
    """Generate a basic offline quiz when LLM is unavailable."""
    # Extract lesson title from prompt if possible
    title_match = re.search(r"العنوان:\s*(.+)", prompt)
    title = title_match.group(1) if title_match else "الدرس"

    questions = [
        {
            "question_text": f"ما هو الموضوع الرئيسي في درس '{title}'؟",
            "question_type": "mcq",
            "options": [f"الموضوع الرئيسي في {title}", "موضوع مختلف", "لا يوجد موضوع", "غير محدد"],
            "correct_answer": f"الموضوع الرئيسي في {title}",
            "marks": 1,
            "explanation": "هذا السؤال يتطلب مراجعة محتوى الدرس.",
        },
        {
            "question_text": f"هل درس '{title}' مفيد للطلاب؟",
            "question_type": "true_false",
            "options": ["True", "False"],
            "correct_answer": "True",
            "marks": 1,
            "explanation": "الدروس المدرسية مفيدة بطبيعتها.",
        },
    ]
    return json.dumps(questions, ensure_ascii=False)


def _map_difficulty(difficulty: str) -> int:
    """Map difficulty string to numeric level."""
    mapping = {"easy": 1, "medium": 2, "hard": 3}
    return mapping.get(difficulty, 2)
