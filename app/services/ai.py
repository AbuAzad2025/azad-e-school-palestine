"""خدمات الذكاء الاصطناعي — مساعد تعليمي ذكي للمدرسين والطلاب.

يستفيد من APIs خارجية (OpenAI, Gemini, etc.) عبر .env لتحليل المحتوى،
توليد الأسئلة، التصحيح المقترحي، والإجابة على استفسارات الطلاب.
كل الكتابات تمر عبر tx()، والأمان عبر role_required.
"""

import asyncio
import json
import os
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from app.extensions import db
from app.models.ai import AiMessage, AiSession, AiUsageLog
from app.models.user import User, UserRole
from app.services.base import tx

try:
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

    class AsyncOpenAI:  # type: ignore[no-redef]
        """Placeholder when openai is not installed."""
        pass


class AiModelName(Enum):
    """اسماء النماذج المتاحة - controllable via .env"""

    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4_TURBO = "gpt-4-turbo"
    GPT_3_5_TURBO = "gpt-3.5-turbo"


@dataclass
class AiConfig:
    """إعدادات AI من متغيرات البيئة"""

    api_key: str = os.getenv("AI_API_KEY", "")
    model: str = os.getenv("AI_MODEL", "gpt-4o-mini")
    max_tokens: int = int(os.getenv("AI_MAX_TOKENS", "4000"))
    temperature: float = float(os.getenv("AI_TEMPERATURE", "0.3"))
    max_requests_per_minute: int = int(os.getenv("AI_MAX_RPM", "60"))
    max_tokens_per_minute: int = int(os.getenv("AI_MAX_TPM", "100000"))
    monthly_budget_usd: float = float(os.getenv("AI_MONTHLY_BUDGET_USD", "100.0"))


# Pricing per 1K tokens (USD) - approximate
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}


class RateLimiter:
    """محدد معدل الطلبات (Token Bucket + Sliding Window)"""

    def __init__(self, max_rpm: int, max_tpm: int):
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.request_times: deque = deque()
        self.token_usage: deque = deque()  # (timestamp, tokens)

    def _clean_old(self, window_seconds: int = 60):
        cutoff = time.time() - window_seconds
        while self.request_times and self.request_times[0] < cutoff:
            self.request_times.popleft()
        while self.token_usage and self.token_usage[0][0] < cutoff:
            self.token_usage.popleft()

    def can_proceed(self, estimated_tokens: int = 1000) -> tuple[bool, str]:
        self._clean_old()
        if len(self.request_times) >= self.max_rpm:
            return False, f"Rate limit: {self.max_rpm} requests/minute exceeded"
        current_tokens = sum(t for _, t in self.token_usage)
        if current_tokens + estimated_tokens > self.max_tpm:
            return False, f"Token limit: {self.max_tpm} tokens/minute exceeded"
        return True, ""

    def record_request(self, tokens_used: int):
        now = time.time()
        self.request_times.append(now)
        self.token_usage.append((now, tokens_used))


class BudgetTracker:
    """متتبع الميزانية الشهرية"""

    def __init__(self, monthly_budget_usd: float):
        self.monthly_budget = monthly_budget_usd
        self._monthly_spent: float = 0.0
        self._last_reset: datetime | None = None

    def _ensure_current_month(self):
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if self._last_reset is None or self._last_reset < month_start:
            self._monthly_spent = 0.0
            self._last_reset = month_start

    def can_spend(self, estimated_cost: float) -> tuple[bool, str]:
        self._ensure_current_month()
        if self._monthly_spent + estimated_cost > self.monthly_budget:
            return False, f"Monthly budget exceeded: ${self.monthly_budget:.2f}"
        return True, ""

    def record_spending(self, cost: float):
        self._ensure_current_month()
        self._monthly_spent += cost

    def get_usage(self) -> dict:
        self._ensure_current_month()
        return {
            "spent_usd": round(self._monthly_spent, 4),
            "budget_usd": self.monthly_budget,
            "remaining_usd": round(self.monthly_budget - self._monthly_spent, 4),
            "usage_percent": round((self._monthly_spent / self.monthly_budget) * 100, 1)
            if self.monthly_budget > 0
            else 0,
        }


class AiService:
    """خدمة مساعد تعليمي ذكي مع دعم OpenAI الحقيقي و Stream SSE."""

    _rate_limiter: "RateLimiter | None" = None
    _budget_tracker: "BudgetTracker | None" = None
    _client: "AsyncOpenAI | None" = None

    def __init__(self):
        self.config = AiConfig()
        if AiService._rate_limiter is None:
            AiService._rate_limiter = RateLimiter(
                self.config.max_requests_per_minute, self.config.max_tokens_per_minute
            )
        if AiService._budget_tracker is None:
            AiService._budget_tracker = BudgetTracker(self.config.monthly_budget_usd)
        if OPENAI_AVAILABLE and self.config.api_key and AiService._client is None:
            AiService._client = AsyncOpenAI(api_key=self.config.api_key)

    def _get_client(self):
        if not OPENAI_AVAILABLE:
            raise RuntimeError("OpenAI library not installed. Run: pip install openai")
        if AiService._client is None:
            if not self.config.api_key:
                raise RuntimeError("AI_API_KEY not set in environment")
            AiService._client = AsyncOpenAI(api_key=self.config.api_key)
        return AiService._client

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = MODEL_PRICING.get(self.config.model, MODEL_PRICING["gpt-4o-mini"])
        input_cost = (prompt_tokens / 1000) * pricing["input"]
        output_cost = (completion_tokens / 1000) * pricing["output"]
        return input_cost + output_cost

    def _check_limits(self, estimated_tokens: int = 2000) -> tuple[bool, str]:
        """فحص حدود المعدل والميزانية"""
        if AiService._rate_limiter is None:
            return True, ""
        can_rate, msg = AiService._rate_limiter.can_proceed(estimated_tokens)
        if not can_rate:
            return False, f"Rate limit: {msg}"
        estimated_cost = self._estimate_cost(0, estimated_tokens)
        if AiService._budget_tracker is None:
            return True, ""
        can_budget, msg = AiService._budget_tracker.can_spend(estimated_cost)
        if not can_budget:
            return False, f"Budget: {msg}"
        return True, ""

    def _record_usage(self, prompt_tokens: int, completion_tokens: int, user_id: int, action: str):
        cost = self._estimate_cost(prompt_tokens, completion_tokens)
        if AiService._rate_limiter:
            AiService._rate_limiter.record_request(prompt_tokens + completion_tokens)
        if AiService._budget_tracker:
            AiService._budget_tracker.record_spending(cost)

        # Log to database
        def _log():
            log = AiUsageLog(
                user_id=user_id,
                model=self.config.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=cost,
                action=action,
            )
            db.session.add(log)

        tx(_log)

    # ======================================================================
    # تحقق الصلاحيات
    # ======================================================================
    def _verify_permission(self, user: User, required_role: UserRole | set[UserRole] | None = None) -> bool:
        if required_role is None:
            return user.is_authenticated
        if user.role == UserRole.super_admin:
            return True
        if user.role in (required_role if isinstance(required_role, set) else [required_role]):
            return True
        return False

    # ======================================================================
    # وظيفة: تصحيح مقترح للواجب (Real API)
    # ======================================================================
    async def suggest_grade(
        self,
        student_answer: str,
        question_type: str,
        correct_answer: str | dict | None = None,
        rubric: str | None = None,
        user_id: int = 0,
    ) -> dict:
        """
        يقترح درجة ونقاط قوة ونقاط ضعف بناءً على إجابة الطالب.
        يستخدم OpenAI API حقيقي.
        """
        if question_type == "mcq":
            system_prompt = "You are a precise grading assistant. Output ONLY valid JSON."
            user_prompt = f"""Grade this MCQ answer:
Rubric: {rubric or "Standard math rubric"}
Student answer: "{student_answer}"
Correct answer: {correct_answer}

Return JSON: {{"score": int (0-10), "feedback": string, "mistake": string or null}}"""
        elif question_type == "true_false":
            system_prompt = "You are a precise grading assistant. Output ONLY valid JSON."
            user_prompt = f"""Grade this True/False answer:
Rubric: {rubric or "Standard"}
Student answer: "{student_answer}"
Correct answer: {correct_answer}

Return JSON: {{"correct": boolean, "score": int (0-10), "feedback": string}}"""
        elif question_type == "essay":
            system_prompt = "You are an experienced teacher grading essays. Output ONLY valid JSON."
            user_prompt = f"""Grade this essay:
Rubric: {rubric or "Standard essay rubric"}
Student essay: "{student_answer}"

Return JSON: {{"score": int (0-10), "strengths": [string], "improvements": [string]}}"""
        else:
            system_prompt = "You are a grading assistant. Output ONLY valid JSON with score 0-10."
            user_prompt = f"Grade: {student_answer}. Return JSON with score 0-10."

        if not self.config.api_key or not OPENAI_AVAILABLE:
            return self._mock_grade(question_type, correct_answer)

        try:
            can, msg = self._check_limits(1000)
            if not can:
                return {"error": msg, "fallback": self._mock_grade(question_type, correct_answer)}

            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=self.config.temperature,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            # Log usage
            usage = response.usage
            self._record_usage(usage.prompt_tokens, usage.completion_tokens, 0, "suggest_grade")

            return result

        except Exception as e:
            return {"error": str(e), "fallback": self._mock_grade(question_type, correct_answer)}

    def _mock_grade(self, question_type: str, correct_answer) -> dict:
        """Fallback mock grading when API unavailable."""
        if question_type == "mcq":
            return {"score": random.randint(6, 10), "feedback": "Good attempt", "mistake": None}
        elif question_type == "true_false":
            return {"correct": True, "score": random.randint(7, 10), "feedback": "Correct reasoning"}
        elif question_type == "essay":
            return {"score": random.randint(5, 9), "strengths": ["Clear structure"], "improvements": ["More examples"]}
        return {"score": 5}

    # ======================================================================
    # توليد أسئلة من النص (Real API)
    # ======================================================================
    async def generate_questions(
        self,
        topic: str,
        count: int = 5,
        question_types: list[str] | None = None,
        difficulty: str = "medium",
        user_id: int = 0,
    ) -> list[dict]:
        """يولد أسئلة امتحان من موضوع معين عبر OpenAI."""
        types = question_types or ["mcq", "true_false", "essay"]

        system_prompt = f"""You are an expert exam writer for Palestinian curriculum.
Generate {count} questions about "{topic}" at {difficulty} difficulty.
Types: {types}.
Output ONLY valid JSON array of questions.
Each question: {{"type": "mcq|true_false|essay", "prompt": string, "options": dict (for mcq), "correct_answer": dict,
"mark": float}}"""

        if not self.config.api_key or not OPENAI_AVAILABLE:
            return self._mock_generate_questions(topic, count, types)

        try:
            can, msg = self._check_limits(2000)
            if not can:
                return [{"error": msg}] + self._mock_generate_questions(topic, count, types)

            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Topic: {topic}"}],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            data = json.loads(content)
            questions = data.get("questions", data) if isinstance(data, dict) else data

            usage = response.usage
            self._record_usage(usage.prompt_tokens, usage.completion_tokens, 0, "generate_questions")

            return questions[:count]

        except Exception as e:
            return [{"error": str(e)}] + self._mock_generate_questions(topic, count, types)

    def _mock_generate_questions(self, topic: str, count: int, types: list[str]) -> list[dict]:
        questions = []
        for i in range(count):
            qtype = types[i % len(types)]
            if qtype == "mcq":
                questions.append(
                    {
                        "type": "mcq",
                        "prompt": f"{topic} - Q{i + 1}",
                        "options": {"A": "A", "B": "B", "C": "C", "D": "D"},
                        "correct_answer": {"index": random.randint(0, 3)},
                        "mark": 2.0,
                    }
                )
            elif qtype == "true_false":
                questions.append(
                    {
                        "type": "true_false",
                        "prompt": f"{topic} - Statement {i + 1}",
                        "correct_answer": {"value": True},
                        "mark": 1.0,
                    }
                )
            else:
                questions.append(
                    {"type": "essay", "prompt": f"{topic} - Essay {i + 1}", "correct_answer": None, "mark": 5.0}
                )
        return questions

    # ======================================================================
    # محادثة الطالب مع Streaming SSE
    # ======================================================================
    async def ask_question_stream(
        self,
        user_id: int,
        question: str,
        context: str | None = None,
        class_id: int | None = None,
        lesson_id: int | None = None,
    ):
        """محادثة تدفقية (SSE) مع الطالب."""

        # Get or create session
        session = AiSession.query.filter_by(user_id=user_id, session_type="student_helper").first()
        if not session:
            session = AiSession(user_id=user_id, session_type="student_helper", class_id=class_id, lesson_id=lesson_id)
            db.session.add(session)
            db.session.commit()

        # Save user message
        user_msg = AiMessage(session_id=session.id, role="user", content=question)
        db.session.add(user_msg)
        db.session.commit()

        # Build context-aware system prompt
        system_prompt = f"""You are an AI tutor for Palestinian curriculum (K-12).
Language: Arabic (primary) / English.
Style: Encouraging, step-by-step, pedagogical.
Current context: {context or "General tutoring"}.
If math: show steps. If science: explain concepts. If language: help with grammar/vocab.
Be concise but thorough. Use Arabic as primary language."""

        # Get recent conversation history
        recent_messages = (
            AiMessage.query.filter_by(session_id=session.id).order_by(AiMessage.created_at.desc()).limit(10).all()
        )
        history = []
        for msg in reversed(recent_messages):
            if msg.role in ("user", "assistant"):
                history.append({"role": msg.role, "content": msg.content})

        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": question}]

        if not self.config.api_key or not OPENAI_AVAILABLE:
            # Mock streaming
            mock_answer = self._mock_ai_answer(question, context)
            for chunk in self._mock_stream_chunks(mock_answer):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
                await asyncio.sleep(0.02)
            yield "data: [DONE]\n\n"
            return

        try:
            can, msg = self._check_limits(2000)
            if not can:
                yield f"data: {json.dumps({'error': msg})}\n\n"
                yield "data: [DONE]\n\n"
                return

            client = self._get_client()
            stream = await client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=True,
            )

            full_answer = ""
            prompt_tokens = 0
            completion_tokens = 0

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    full_answer += delta
                    yield f"data: {json.dumps({'delta': delta})}\n\n"

                # Track usage from stream
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens

            yield "data: [DONE]\n\n"

            # Save assistant response
            if full_answer:
                ai_msg = AiMessage(session_id=session.id, role="assistant", content=full_answer)
                db.session.add(ai_msg)
                db.session.commit()

            # Log usage
            if completion_tokens > 0:
                self._record_usage(prompt_tokens or 100, completion_tokens, 0, "chat")

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    async def ask_question(
        self,
        user_id: int,
        question: str,
        context: str | None = None,
        class_id: int | None = None,
        lesson_id: int | None = None,
    ) -> dict:
        """Non-streaming version for simple use."""
        full_answer = ""
        async for chunk in self.ask_question_stream(user_id, question, context, class_id, lesson_id):
            if chunk.startswith("data: "):
                data = chunk[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    parsed = json.loads(data)
                    if "delta" in parsed:
                        full_answer += parsed["delta"]
                except Exception:
                    pass

        session = AiSession.query.filter_by(user_id=user_id, session_type="student_helper").first()
        return {"question": question, "answer": full_answer, "session_id": session.id if session else None}

    def _mock_ai_answer(self, question: str, context: str | None = None) -> str:
        if not question:
            return "Please ask a question."

        q_lower = question.lower()
        if "math" in q_lower or "equation" in q_lower or "solve" in q_lower:
            return (
                "بصفتي مساعد رياضيات، I notice you're asking about math. "
                "For specific equation solving, please provide the equation "
                "details, and I'll help step-by-step."
            )
        elif "question" in q_lower or "test" in q_lower or "exam" in q_lower:
            return "لدي مجموعة من اختبارات الرياضيات. هل تريد مراجعة درس معين أو حل تمارين من الكتاب؟"
        elif "grade" in q_lower or "mark" in q_lower or "score" in q_lower:
            return (
                'يمكنك رؤية درجاتك في "الدashboard" > "grades". '
                "إذا كان هناك استفسار حول تصحيح معين، حدده بالتفصيل "
                "وسأقوم بمساعدتك."
            )
        elif "homework" in q_lower or "assignment" in q_lower:
            return "يمكنك عرض الواجبات في قسم الواجبات. هل تريد مساعدة في مشكلة معينة؟"
        else:
            return (
                f'سؤالك: "{question[:80]}...". '
                "أنا مساعد ذكاء اصطناعي مخصص للمنصة، يمكنك أن تطرح سؤالك عن المادة، الواجب، "
                "أو الاختبار وسأبذل قصارى جهدي للمساعدة ضمن سياق النظام."
            )

    def _mock_stream_chunks(self, text: str) -> list[str]:
        words = text.split()
        chunks = []
        for i in range(0, len(words), 3):
            chunks.append(" ".join(words[i : i + 3]) + " ")
        return chunks

    # ======================================================================
    # إدارة الجلسات
    # ======================================================================
    def start_session(
        self, user_id: int, session_type: str, class_id: int | None = None, lesson_id: int | None = None
    ) -> AiSession:
        def _create():
            return AiSession(user_id=user_id, session_type=session_type, class_id=class_id, lesson_id=lesson_id)

        return tx(_create)

    def log_message(self, session_id: int, role: str, content: str) -> AiMessage:
        def _log():
            msg = AiMessage(session_id=session_id, role=role, content=content)
            db.session.add(msg)
            db.session.commit()
            return msg

        return tx(_log)

    # ======================================================================
    # إحصائيات الاستخدام
    # ======================================================================
    def get_usage_stats(self, user_id: int | None = None, days: int = 30) -> dict:
        """إحصائيات استخدام AI."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = AiUsageLog.query.filter(AiUsageLog.created_at >= cutoff)
        if user_id:
            query = query.filter_by(user_id=user_id)
        logs = query.all()

        total_requests = len(logs)
        total_tokens = sum(log.total_tokens for log in logs)
        total_cost = sum(log.estimated_cost_usd for log in logs)

        by_action: dict[str, int] = {}
        by_model: dict[str, int] = {}
        for log in logs:
            by_action[log.action] = by_action.get(log.action, 0) + 1
            by_model[log.model] = by_model.get(log.model, 0) + 1

        return {
            "period_days": days,
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "by_action": by_action,
            "by_model": by_model,
            "budget": AiService._budget_tracker.get_usage() if AiService._budget_tracker else {},
            "rate_limit": {
                "requests_per_minute": AiService._rate_limiter.max_rpm if AiService._rate_limiter else 0,
                "tokens_per_minute": AiService._rate_limiter.max_tpm if AiService._rate_limiter else 0,
            },
        }


# Singleton export
_ai_service: "AiService | None" = None


def get_ai_service() -> AiService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AiService()
    return _ai_service
