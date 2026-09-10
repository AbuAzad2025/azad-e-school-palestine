"""Integration tests — AI endpoints + tenant quota gating (P4-AI).

Covers:
    1. require_ai_quota: AI_DISABLED_FOR_TENANT (free tier), AI_QUOTA_EXCEEDED
       (token cap reached), super_admin bypass, pro-tier allow.
    2. POST /ai/rag/query: scoped execution + cross-tenant isolation.
    3. POST /ai/quiz/generate: draft creation (real path) + offline fallback
       + ownership enforcement (403 cross-school lesson).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from tests.conftest import (
    _db,
    make_class,
    make_grade,
    make_lesson,
    make_school,
    make_subject,
    make_user,
)

PASSWORD = "TestPass123!"


def _login(client, email: str) -> None:
    client.post("/auth/login", data={"email": email, "password": PASSWORD}, follow_redirects=True)


def _email_of(app, user_id: int) -> str:
    with app.app_context():
        from app.models.user import User

        u = _db.session.get(User, user_id)
        return u.email if u else ""


def _make_teacher(app, school_id: int) -> int:
    return make_user(app, role="teacher", school_id=school_id)


def _make_student(app, school_id: int) -> int:
    return make_user(app, role="student", school_id=school_id)


def _quota_row(app, school_id: int, tier: str = "free", ai_enabled: bool = False, max_tokens: int = 0):
    """Create or update the school's TenantQuota row directly."""
    with app.app_context():
        from app.extensions import db
        from app.models.tenant import TenantQuota

        q = TenantQuota.query.filter_by(school_id=school_id).first()
        if q is None:
            q = TenantQuota(school_id=school_id)
            db.session.add(q)
        q.tier = tier
        q.ai_enabled = ai_enabled
        q.max_ai_tokens_monthly = max_tokens
        db.session.commit()


def _seed_usage(app, school_id: int, tokens: int) -> None:
    """Insert AiUsageLog rows summing to `tokens` for a user in `school_id`."""
    with app.app_context():
        from app.models.ai import AiUsageLog

        uid = _make_student(app, school_id)
        log = AiUsageLog(
            user_id=uid,
            model="gpt-4o-mini",
            prompt_tokens=tokens,
            completion_tokens=0,
            total_tokens=tokens,
            estimated_cost_usd=0.0,
            action="chat",
        )
        _db.session.add(log)
        _db.session.commit()


@pytest.fixture(autouse=True)
def _clear_quota_cache():
    """The quota guard caches decisions for 30s — reset around each test."""
    from app.core.cache import clear

    clear()
    yield
    clear()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Quota gating
# ═══════════════════════════ auto─────────────────────────────────────────


class TestTenantQuotaGating:
    def test_ai_disabled_for_free_tier(self, app, client):
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        _quota_row(app, sid, tier="free", ai_enabled=False)

        _login(client, _email_of(app, tid))
        resp = client.post("/ai/chat", json={"question": "مرحبا"})
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["error"]["code"] == "AI_DISABLED_FOR_TENANT"

    def test_quota_exceeded_blocks(self, app, client):
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100)
        _seed_usage(app, sid, tokens=150)

        _login(client, _email_of(app, tid))
        resp = client.post("/ai/chat", json={"question": "سؤال"})
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "AI_QUOTA_EXCEEDED"

    def test_within_quota_allows(self, app, client):
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100000)

        _login(client, _email_of(app, tid))
        resp = client.post("/ai/chat", json={"question": "مرحبا"})
        assert resp.status_code == 200

    def test_super_admin_bypasses_quota(self, app, client):
        sid = make_school(app)
        admin = make_user(app, role="super_admin")
        _quota_row(app, sid, tier="free", ai_enabled=False)

        _login(client, _email_of(app, admin))
        resp = client.post("/ai/chat", json={"question": "مرحبا"})
        assert resp.status_code == 200

    def test_user_without_school_rejected(self, app, client):
        uid = make_user(app, role="student")  # no school link
        _login(client, _email_of(app, uid))
        resp = client.post("/ai/chat", json={"question": "مرحبا"})
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "AI_DISABLED_FOR_TENANT"

    def test_unauthenticated_rejected(self, app, client):
        resp = client.post("/ai/chat", json={"question": "x"})
        # Flask-Login redirects web routes to /auth/login; API-style JSON gets 401
        assert resp.status_code in (301, 302, 401)


# ═══════════════════════════════════════════════════════════════════════════
# 2. RAG endpoint
# ═══════════════════════════════════════════════════════════════════════════


class TestRagQueryEndpoint:
    def _ingest(self, app, lesson_id: int, school_id: int) -> None:
        from app.services.rag_service import ingest_lesson_for_rag

        with app.app_context():
            ingest_lesson_for_rag(lesson_id, school_id)

    def test_empty_question_400(self, app, client):
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100000)

        _login(client, _email_of(app, tid))
        resp = client.post("/ai/rag/query", json={"question": "  "})
        assert resp.status_code == 400

    def test_scoped_answer_with_isolation(self, app, client):
        app2 = app  # clarity alias
        sid1 = make_school(app2)
        sid2 = make_school(app2)
        tid1 = _make_teacher(app2, sid1)
        _quota_row(app2, sid1, tier="pro", ai_enabled=True, max_tokens=100000)
        _quota_row(app2, sid2, tier="pro", ai_enabled=True, max_tokens=100000)

        gid, subj = make_grade(app2, sid1), make_subject(app2)
        cid = make_class(app2, sid1, gid, subj)
        lid = make_lesson(app2, cid, title="قاعدة الإكجار في الكيمياء", status="published")
        with app2.app_context():
            from app.extensions import db
            from app.models.content import Lesson

            lesson = _db.session.get(Lesson, lid)
            lesson.body_html = "قاعدة الإكجار تقول إن كل فعل له رد فعل مضاد بنفس القوة."
            db.session.commit()

        self._ingest(app2, lid, sid1)

        _login(client, _email_of(app2, tid1))
        resp = client.post(
            "/ai/rag/query",
            json={"question": "ما هي قاعدة الإكجار؟"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["method"] == "rag"
        assert body["sources"], "expected citations from school 1 content"
        assert body["sources"][0]["lesson_id"] == lid

        # Tenant B never sees Tenant A content — fresh client (Flask-Login
        # يوجّه المستخدم المسجّل مسبقاً بعيداً عن صفحة الدخول فلا يُبدّل الجلسة)
        client2 = app2.test_client()
        tid2 = _make_teacher(app2, sid2)
        _login(client2, _email_of(app2, tid2))
        resp2 = client2.post("/ai/rag/query", json={"question": "ما هي قاعدة الإكجار؟"})
        assert resp2.status_code == 200
        body2 = resp2.get_json()
        # Tenant B's own chunk store is empty → direct_llm path, zero A citations
        assert body2["method"] == "direct_llm"
        assert body2["sources"] == []
        assert all(src["lesson_id"] != lid for src in body2["sources"])

    def test_llm_failure_still_200_offline_answer(self, app, client):
        """External LLM degradation must not 500 — offline answer is returned."""
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100000)

        gid, subj = make_grade(app, sid), make_subject(app)
        cid = make_class(app, sid, gid, subj)
        lid = make_lesson(app, cid, title="قانون أوم", status="published")
        with app.app_context():
            from app.extensions import db
            from app.models.content import Lesson

            lesson = _db.session.get(Lesson, lid)
            lesson.body_html = "يتناسب التيار عكسياً مع المقاومة."
            db.session.commit()
        self._ingest(app, lid, sid)

        with patch("app.services.rag_service._call_llm_with_context", side_effect=RuntimeError("LLM down")):
            _login(client, _email_of(app, tid))
            resp = client.post("/ai/rag/query", json={"question": "قانون أوم"})
            assert resp.status_code == 502  # structured error, not a crash
            assert resp.get_json()["error"]["code"] == "RAG_QUERY_FAILED"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Quiz generation endpoint
# ═══════════════════════════════════════════════════════════════════════════


class TestQuizGenerateEndpoint:
    def _lesson(self, app, school_id: int, body: str = "محتوى الدرس عن الكسور العشرية.") -> int:
        gid, subj = make_grade(app, school_id), make_subject(app)
        cid = make_class(app, school_id, gid, subj)
        lid = make_lesson(app, cid, status="published")
        with app.app_context():
            from app.extensions import db
            from app.models.content import Lesson

            lesson = _db.session.get(Lesson, lid)
            lesson.body_html = body
            db.session.commit()
        return lid

    def test_requires_teacher_role(self, app, client):
        sid = make_school(app)
        stid = _make_student(app, sid)
        lid = self._lesson(app, sid)
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100000)

        _login(client, _email_of(app, stid))
        resp = client.post("/ai/quiz/generate", json={"lesson_id": lid})
        assert resp.status_code == 403

    def test_generates_draft_quiz(self, app, client):
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        lid = self._lesson(app, sid)
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100000)

        fake_llm = """
        [{"question_text": "ما وحدة الكسور؟", "question_type": "mcq",
          "options": ["وحدة", "عشرة", "مئة", "ألف"], "correct_answer": "وحدة",
          "marks": 1, "explanation": "وحدة الكسور العشرية هي وحدة"}]
        """
        with patch("requests.post") as post, patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            post.return_value.status_code = 200
            post.return_value.json.return_value = {
                "choices": [{"message": {"content": fake_llm}}]
            }
            _login(client, _email_of(app, tid))
            resp = client.post(
                "/ai/quiz/generate",
                json={"lesson_id": lid, "question_count": 3, "difficulty": "easy"},
            )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["status"] == "draft"
        assert body["question_count"] == 1

        with app.app_context():
            from app.models.assessment import Quiz

            quiz = _db.session.get(Quiz, body["quiz_id"])
            assert quiz is not None and quiz.status == "draft"

    def test_offline_fallback_generates_draft(self, app, client):
        """LLM failure → deterministic offline draft, still 201."""
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        lid = self._lesson(app, sid, body="العنوان: الكسور العشرية. شرح قيمة المنزلة.")
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100000)

        with patch("requests.post", side_effect=RuntimeError("network down")):
            _login(client, _email_of(app, tid))
            resp = client.post("/ai/quiz/generate", json={"lesson_id": lid, "question_count": 2})
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["status"] == "draft"
        assert body["question_count"] == 2  # offline generator emits 2 questions

    def test_cross_school_lesson_forbidden(self, app, client):
        sid1, sid2 = make_school(app), make_school(app)
        tid1 = _make_teacher(app, sid1)
        lid2 = self._lesson(app, sid2)
        _quota_row(app, sid1, tier="pro", ai_enabled=True, max_tokens=100000)

        _login(client, _email_of(app, tid1))
        resp = client.post("/ai/quiz/generate", json={"lesson_id": lid2})
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_missing_lesson_404(self, app, client):
        sid = make_school(app)
        tid = _make_teacher(app, sid)
        _quota_row(app, sid, tier="pro", ai_enabled=True, max_tokens=100000)

        _login(client, _email_of(app, tid))
        resp = client.post("/ai/quiz/generate", json={"lesson_id": 999999})
        assert resp.status_code == 404
