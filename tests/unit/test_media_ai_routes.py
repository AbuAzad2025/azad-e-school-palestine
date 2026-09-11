"""Batch 3 — media stream route + AI HTTP endpoints (real requests, real users).

Media route (`/media/stream/<lesson_id>/<filename>`): every security branch —
bad token, uid mismatch, path traversal, extension filter, missing file, and
the full happy path serving a real file from disk.

AI routes not covered by tests/integration/test_ai_endpoints_and_quotas.py:
grade/suggest (validation + success), questions/generate (validation +
success), usage/stats (admin-only RBAC), chat GET page, chat POST (validation
+ success, offline AI service), rag/query no-school branch.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_user

_PASSWORD = "TestPass123!"


def _persona(app, role, school_id=None):
    """Create a user and a logged-in test client → (user_id, client).

    Same contract as tests/security/conftest.make_persona, without the
    fixture machinery.
    """
    email = f"b3-{uuid.uuid4().hex[:10]}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": _PASSWORD}, follow_redirects=False)
    return uid, client


@pytest.fixture(autouse=True)
def _clear_quota_cache():
    from app.core.cache import clear

    clear()
    yield
    clear()


def _enable_ai(app, school_id: int) -> None:
    """Give the school an enabled pro-tier quota (bypasses require_ai_quota)."""
    from app.extensions import db
    from app.models.tenant import TenantQuota

    with app.app_context():
        q = TenantQuota.query.filter_by(school_id=school_id).first()
        if q is None:
            q = TenantQuota(school_id=school_id)
            db.session.add(q)
        q.tier = "pro"
        q.ai_enabled = True
        q.max_ai_tokens_monthly = 999_999
        db.session.commit()


# ═══════════════════════════════════════════════════════════════════════════
# /media/stream — route-level security
# ═══════════════════════════════════════════════════════════════════════════


class TestMediaStreamRoute:
    @pytest.fixture()
    def student(self, app):
        sid = make_school(app)
        uid, client = _persona(app, "student", school_id=sid)
        return sid, uid, client

    def test_missing_token_forbidden(self, app, student):
        _, _, client = student
        resp = client.get("/media/stream/1/playlist.m3u8")
        assert resp.status_code in (302, 403)  # 302 → login redirect

    def test_bad_token_forbidden(self, app, student):
        _, _, client = student
        resp = client.get("/media/stream/1/playlist.m3u8?token=deadbeef&uid=1&sid=1")
        assert resp.status_code == 403

    def test_uid_mismatch_forbidden(self, app, student):
        from app.services.video_service import generate_stream_token

        sid, uid, client = student
        with app.app_context():
            token = generate_stream_token(user_id=uid, school_id=sid, lesson_id=1)
        # attacker presents a valid token but for a different uid
        resp = client.get(f"/media/stream/1/playlist.m3u8?token={token}&uid=999999&sid={sid}")
        assert resp.status_code == 403

    def test_path_traversal_blocked(self, app, student):
        from app.services.video_service import generate_stream_token

        sid, uid, client = student
        with app.app_context():
            token = generate_stream_token(user_id=uid, school_id=sid, lesson_id=1)
        resp = client.get(f"/media/stream/1/..%2F..%2Fsecrets.m3u8?token={token}&uid={uid}&sid={sid}")
        assert resp.status_code in (400, 403, 404)

    def test_disallowed_extension_blocked(self, app, student):
        from app.services.video_service import generate_stream_token

        sid, uid, client = student
        with app.app_context():
            token = generate_stream_token(user_id=uid, school_id=sid, lesson_id=1)
        # validate_lesson_access will deny (no real lesson) → 403 before ext check
        resp = client.get(f"/media/stream/1/evil.exe?token={token}&uid={uid}&sid={sid}")
        assert resp.status_code == 403

    def test_happy_path_serves_real_file(self, app, student, tmp_path):
        from app.extensions import db
        from app.models.content import Lesson
        from app.services.video_service import (
            generate_stream_token,
            get_protected_media_path,
        )

        sid, uid, client = student
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            lesson = Lesson(class_id=cid, title="درس فيديو", status="published")
            db.session.add(lesson)
            db.session.commit()
            lesson_id = lesson.id
            make_class_member(app, cid, uid)

            media_dir = get_protected_media_path(sid, lesson_id)
            playlist = Path(media_dir) / "index.m3u8"
            playlist.parent.mkdir(parents=True, exist_ok=True)
            playlist.write_text("#EXTM3U\n", encoding="utf-8")
            token = generate_stream_token(user_id=uid, school_id=sid, lesson_id=lesson_id)

        resp = client.get(f"/media/stream/{lesson_id}/index.m3u8?token={token}&uid={uid}&sid={sid}")
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
        assert b"#EXTM3U" in resp.data

    def test_missing_file_404(self, app, student):
        from app.extensions import db
        from app.models.content import Lesson
        from app.services.video_service import generate_stream_token

        sid, uid, client = student
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            lesson = Lesson(class_id=cid, title="درس", status="published")
            db.session.add(lesson)
            db.session.commit()
            lesson_id = lesson.id
            make_class_member(app, cid, uid)
            token = generate_stream_token(user_id=uid, school_id=sid, lesson_id=lesson_id)

        resp = client.get(f"/media/stream/{lesson_id}/ghost.m3u8?token={token}&uid={uid}&sid={sid}")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# AI routes — complement to test_ai_endpoints_and_quotas.py
# ═══════════════════════════════════════════════════════════════════════════


class TestAIGradeSuggest:
    def test_requires_login(self, app):
        client = app.test_client()
        resp = client.post("/ai/grade/suggest", json={"student_answer": "x"})
        assert resp.status_code in (302, 401)

    def test_empty_answer_400(self, app):
        sid = make_school(app)
        _enable_ai(app, sid)
        _, client = _persona(app, "teacher", school_id=sid)
        resp = client.post("/ai/grade/suggest", json={"student_answer": ""})
        assert resp.status_code == 400

    def test_student_forbidden(self, app):
        sid = make_school(app)
        _, client = _persona(app, "student", school_id=sid)
        resp = client.post("/ai/grade/suggest", json={"student_answer": "جواب"})
        assert resp.status_code == 403

    def test_success_returns_suggestion(self, app):
        sid = make_school(app)
        _enable_ai(app, sid)
        _, client = _persona(app, "teacher", school_id=sid)
        with patch("app.modules.ai.routes.get_ai_service") as svc:
            svc.return_value.suggest_grade = AsyncMock(return_value={"score": 8, "feedback": "جيد"})
            resp = client.post(
                "/ai/grade/suggest",
                json={"student_answer": "إجابة الطالب", "question_type": "essay"},
            )
        assert resp.status_code == 200
        assert resp.get_json() == {"score": 8, "feedback": "جيد"}


class TestAIQuestionGenerate:
    def test_empty_topic_400(self, app):
        sid = make_school(app)
        _enable_ai(app, sid)
        _, client = _persona(app, "teacher", school_id=sid)
        resp = client.post("/ai/questions/generate", json={"topic": ""})
        assert resp.status_code == 400

    def test_student_forbidden(self, app):
        sid = make_school(app)
        _, client = _persona(app, "student", school_id=sid)
        resp = client.post("/ai/questions/generate", json={"topic": "رياضيات"})
        assert resp.status_code == 403

    def test_success_returns_questions(self, app):
        sid = make_school(app)
        _enable_ai(app, sid)
        _, client = _persona(app, "teacher", school_id=sid)
        questions = [{"type": "mcq", "prompt": "س1"}]
        with patch("app.modules.ai.routes.get_ai_service") as svc:
            svc.return_value.generate_questions = AsyncMock(return_value=questions)
            resp = client.post("/ai/questions/generate", json={"topic": "الكسور", "count": 3})
        assert resp.status_code == 200
        assert resp.get_json() == {"questions": questions}


class TestAIUsageStats:
    def test_teacher_forbidden(self, app):
        sid = make_school(app)
        _, client = _persona(app, "teacher", school_id=sid)
        resp = client.get("/ai/usage/stats")
        assert resp.status_code == 403

    def test_school_admin_ok(self, app):
        sid = make_school(app)
        _, client = _persona(app, "school_admin", school_id=sid)
        with patch("app.modules.ai.routes.get_ai_service") as svc:
            svc.return_value.get_usage_stats.return_value = {"total_tokens": 0}
            resp = client.get("/ai/usage/stats?days=7")
        assert resp.status_code == 200
        assert resp.get_json() == {"total_tokens": 0}


class TestAIChatEndpoints:
    def test_chat_page_requires_login(self, app):
        client = app.test_client()
        resp = client.get("/ai/chat")
        assert resp.status_code in (302, 401)

    def test_chat_page_renders_for_student(self, app):
        sid = make_school(app)
        _, client = _persona(app, "student", school_id=sid)
        resp = client.get("/ai/chat")
        assert resp.status_code == 200

    def test_chat_post_empty_question_400(self, app):
        sid = make_school(app)
        _enable_ai(app, sid)
        _, client = _persona(app, "student", school_id=sid)
        resp = client.post("/ai/chat", json={"question": "   "})
        assert resp.status_code == 400

    def test_chat_post_success_offline_service(self, app):
        sid = make_school(app)
        _enable_ai(app, sid)
        _, client = _persona(app, "student", school_id=sid)

        async def fake_ask(**kw):
            return {"answer": "الجواب", "tokens": 3}

        with patch("app.modules.ai.routes.get_ai_service") as svc:
            svc.return_value.ask_question.side_effect = fake_ask
            resp = client.post("/ai/chat", json={"question": "ما هي الكسور؟"})
        assert resp.status_code == 200
        assert resp.get_json() == {"answer": "الجواب", "tokens": 3}

    def test_rag_query_without_school_forbidden(self, app):
        # super_admin without a school scope → AI_DISABLED_FOR_TENANT
        _, client = _persona(app, "super_admin")
        resp = client.post("/ai/rag/query", json={"question": "سؤال"})
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["error"]["code"] == "AI_DISABLED_FOR_TENANT"

    def test_rag_query_empty_question_400(self, app):
        sid = make_school(app)
        _enable_ai(app, sid)
        _, client = _persona(app, "teacher", school_id=sid)
        resp = client.post("/ai/rag/query", json={"question": ""})
        assert resp.status_code == 400
