"""تنقية الأخطاء ومعرّف المتابعة — اختبارات واجهة ``app/core/errors.py``.

القاعدة التي تحميها هذه الاختبارات واحدة: ما يراه المستخدم رسالة عربية آمنة
وقابلة للتنفيذ، وما يراه الفريق التفصيل الكامل — والرابط الوحيد بينهما معرّف
ارتباط. لذلك نختبر: التنقية (SQL/محرّك/مسار ملف لا تصل للمستخدم)، تصنيف
الاستثناءات (ما نعرفه بدقة فقط يُترجَم برمز أدقّ)، شكل الردّ في الحالتين
(JSON للـ API، صفحة عربية لغيره)، وأن المعرّف يظهر في الردّ وفي الترويسة.
"""

from __future__ import annotations

import ast
import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from app.core.errors import (
    error_domain,
    error_payload,
    flash_error,
    hint_for,
    looks_technical,
    map_exception,
    safe_details,
    safe_message,
    standard_hint,
    standard_message,
    wants_json,
)
from flask import Flask, get_flashed_messages

SQL_LEAK = 'psycopg2.errors.UndefinedColumn: column "display_order" does not exist\nLINE 1: SELECT 1 FROM quiz_attempts'


# ═══════════════════════════════════════════════════════════════════════════
# التنقية والتصنيف — منطق نقي بلا طلبات
# ═══════════════════════════════════════════════════════════════════════════
class TestSanitization:
    def test_technical_text_is_detected(self):
        assert looks_technical(SQL_LEAK)
        assert looks_technical('IntegrityError: duplicate key value violates unique constraint "uq_user_role_link"')
        assert looks_technical('Traceback (most recent call last):\n  File "x.py", line 3')
        assert looks_technical("<class 'sqlalchemy.exc.OperationalError'>")

    def test_business_arabic_text_is_not_flagged(self):
        assert not looks_technical("رصيد المحفظة لا يكفي لإتمام التحويل.")
        assert not looks_technical("هذا الاشتراك مُنتهٍ. يرجى التجديد للمتابعة.")

    def test_safe_message_replaces_technical_text(self):
        message = safe_message(500, SQL_LEAK)
        assert message == safe_message(500)
        for token in ("psycopg", "SELECT", "does not exist", "display_order"):
            assert token not in message

    def test_safe_message_keeps_clean_business_text(self):
        assert safe_message(400, "رصيد المحفظة لا يكفي.") == "رصيد المحفظة لا يكفي."

    def test_safe_message_rejects_overlong_text(self):
        assert safe_message(400, "ط" * 400) == safe_message(400)

    def test_payload_shape_carries_request_id_and_no_detail(self, app):
        with app.app_context():
            payload = error_payload(500, message=SQL_LEAK)
        assert set(payload) == {"error", "meta"}
        # domain: التصنيف الدلالي سبب وجوده أن الواجهة تتحرّك على نوع الخطأ
        # (زر دخول على auth، تحديث على conflict) — حقل عقد لا تجميل.
        assert set(payload["error"]) == {"code", "domain", "message", "details"}
        assert payload["error"]["domain"] == "server"
        assert payload["meta"]["request_id"]
        assert payload["meta"]["version"] == "v1"
        assert "psycopg" not in str(payload)


class TestExceptionMapping:
    def test_tx_error_is_a_conflict_with_its_business_message(self):
        from app.core.db import TxError

        status, message, code = map_exception(TxError("تمت مراجعة هذا الدفع مسبقاً."))
        assert (status, code) == (409, "CONFLICT")
        assert message == "تمت مراجعة هذا الدفع مسبقاً."

    def test_unique_violation_is_a_conflict_with_generic_message(self):
        """انتهاك القيد الفريد: تعارض يفهمه المستخدم، وبلا نص القاعدة."""
        from sqlalchemy.exc import IntegrityError

        class _Orig:
            pgcode = "23505"

        status, message, code = map_exception(IntegrityError("stmt", {}, _Orig()))
        assert (status, code) == (409, "CONFLICT")
        assert "uq_" not in message

    def test_other_integrity_error_stays_internal(self):
        """NOT NULL/مفتاح أجنبي عطل برمجي — لا يُلطَّف إلى «خطأ في مدخلاتك»."""
        from sqlalchemy.exc import IntegrityError

        class _Orig:
            pgcode = "23502"

        status, _message, code = map_exception(IntegrityError("stmt", {}, _Orig()))
        assert (status, code) == (500, "INTERNAL_ERROR")

    def test_operational_error_is_service_unavailable(self):
        from sqlalchemy.exc import OperationalError

        status, _message, code = map_exception(OperationalError("stmt", {}, Exception("down")))
        assert (status, code) == (503, "SERVICE_UNAVAILABLE")

    def test_csrf_error_is_a_session_message(self):
        from flask_wtf.csrf import CSRFError

        status, message, code = map_exception(CSRFError("The CSRF token is missing."))
        assert (status, code) == (400, "CSRF_FAILED")
        assert "الجلسة" in message

    def test_unknown_exception_is_a_generic_internal_error(self):
        status, message, code = map_exception(RuntimeError("boom"))
        assert (status, code) == (500, "INTERNAL_ERROR")
        assert "boom" not in message

    def test_wrapped_internal_server_error_uses_the_original(self, error_app):
        """Flask يلفّ خطأ غير متوقع بـ InternalServerError — نصنّف الأصل.

        التصنيف على الأصل لا على اللفّافة: عطل اتصال القاعدة يجب أن يوصل
        503 «الخدمة غير متاحة مؤقتاً»، لا 500 عاماً يحيّر المستخدم.
        """
        from app.core.errors import handle_unexpected_exception
        from sqlalchemy.exc import OperationalError
        from werkzeug.exceptions import InternalServerError

        wrapped = InternalServerError(original_exception=OperationalError("stmt", {}, Exception("down")))
        with error_app.test_request_context("/api/v1/x", headers={"Accept": "application/json"}):
            response, status = handle_unexpected_exception(wrapped)
        assert status == 503
        assert response.get_json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_wants_json_by_path_and_accept(self):
        app = Flask(__name__)
        with app.test_request_context("/api/v1/classes"):
            assert wants_json() is True
        with app.test_request_context("/classes", headers={"Accept": "application/json"}):
            assert wants_json() is True
        with app.test_request_context("/classes", headers={"Accept": "text/html"}):
            assert wants_json() is False
        with app.test_request_context("/health"):
            assert wants_json() is True

    def test_missing_accept_header_is_treated_as_html(self):
        """بلا ترويسة Accept: الافتراضي صفحة عربية لا JSON.

        تراجع حقيقي: ``accept_html`` تعود خطأ عند غياب الترويسة، فكان كل عميل
        لا يرسلها (أدوات داخلية، عميل الاختبار) يستلم جسم JSON من مسار واجهة
        بدل صفحة الخطأ العربية.
        """
        app = Flask(__name__)
        with app.test_request_context("/classes"):
            assert wants_json() is False
        with app.test_request_context("/classes", headers={"Accept": "*/*"}):
            assert wants_json() is False


# ═══════════════════════════════════════════════════════════════════════════
# الطلب الحقيقي — صفحة عربية للـ HTML، JSON للـ API، ومعرّف في كلاهما
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def error_app():
    """تطبيق بمسارات تُطلق أخطاء — وPROPAGATE_EXCEPTIONS مُطفأ عمداً.

    مع ``TESTING=True`` يعيد Flask رفع الاستثناء بدل تحويله إلى 500، فلا يصل
    إلى المعالج العام أصلاً؛ الاختبار يجب أن يمرّ بالمسار الحقيقي.
    """
    from app import create_app

    app = create_app()
    app.config.update(
        TESTING=False,
        PROPAGATE_EXCEPTIONS=False,
        TALISMAN_ENABLED=False,
        RATELIMIT_ENABLED=False,
        WTF_CSRF_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
    )

    @app.get("/adv-boom")
    def adv_boom():
        raise RuntimeError(SQL_LEAK)

    # GET فقط عن قصد: POST عليه يجب أن يُنتج 405 (وليست صفحة Werkzeug إنجليزية)
    @app.get("/adv-get-only")
    def adv_get_only():
        return "ok"

    return app


class TestRealRequests:
    def test_html_500_is_arabic_and_shows_a_tracking_reference(self, error_app):
        resp = error_app.test_client().get("/adv-boom", headers={"Accept": "text/html"})
        body = resp.get_data(as_text=True)
        assert resp.status_code == 500
        assert "رقم المتابعة" in body
        assert resp.headers["X-Request-ID"] in body
        for token in ("psycopg", "SELECT", "Traceback", "display_order"):
            assert token not in body

    def test_api_500_is_json_with_the_same_sanitized_shape(self, error_app):
        resp = error_app.test_client().get("/adv-boom", headers={"Accept": "application/json"})
        payload = resp.get_json()
        assert resp.status_code == 500
        assert payload["error"]["code"] == "INTERNAL_ERROR"
        assert payload["meta"]["request_id"]
        assert "psycopg" not in resp.get_data(as_text=True)

    def test_html_405_is_arabic_not_werkzeug_english(self, error_app):
        resp = error_app.test_client().post("/adv-get-only", headers={"Accept": "text/html"})
        body = resp.get_data(as_text=True)
        assert resp.status_code == 405
        assert "الإجراء غير مدعوم" in body
        assert "method is not allowed" not in body.lower()

    def test_html_error_without_accept_header_still_renders_the_page(self, error_app):
        """طلب بلا ترويسة Accept على مسار واجهة: صفحة عربية لا جسم JSON."""
        resp = error_app.test_client().post("/adv-get-only")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 405
        assert "الإجراء غير مدعوم" in body
        assert not body.lstrip().startswith("{")

    def test_api_405_is_json(self, error_app):
        resp = error_app.test_client().post("/adv-get-only", headers={"Accept": "application/json"})
        assert resp.status_code == 405
        assert resp.get_json()["error"]["code"] == "METHOD_NOT_ALLOWED"

    def test_english_locale_translates_the_standard_message(self, error_app):
        """الترجمة تُطلب وقت الردّ لا عند الاستيراد — فاللغة تتبع الطلب."""
        client = error_app.test_client()
        client.set_cookie("locale", "en")
        resp = client.post("/adv-get-only", headers={"Accept": "application/json"})
        message = resp.get_json()["error"]["message"]
        assert message.startswith("This action is not supported")
        assert message != "هذا الإجراء غير مدعوم في هذا العنوان. يرجى العودة والاستخدام من الواجهة."

    def test_correlation_id_header_matches_the_body(self, error_app):
        resp = error_app.test_client().get("/definitely-missing", headers={"Accept": "application/json"})
        assert resp.headers["X-Request-ID"] == resp.get_json()["meta"]["request_id"]


# ═══════════════════════════════════════════════════════════════════════════
# منافذ التسريب الأخرى — تنبيهات الواجهة (flash) ورسائل الخدمات
# ═══════════════════════════════════════════════════════════════════════════
class TestFlashErrorsAreSanitized:
    """``flash(str(exc))`` كان منفذاً موازياً للـ API: نفس التنقية تُطبَّق هنا."""

    def test_technical_text_is_replaced(self, error_app):
        error_app.secret_key = "test-secret"
        with error_app.test_request_context("/x"):
            flash_error(SQL_LEAK)
            flashed = get_flashed_messages(with_categories=True)
        assert flashed == [("danger", standard_message(400))]

    def test_business_text_and_category_are_preserved(self, error_app):
        error_app.secret_key = "test-secret"
        with error_app.test_request_context("/x"):
            flash_error("رصيد المحفظة لا يكفي.", "warning")
            flashed = get_flashed_messages(with_categories=True)
        assert flashed == [("warning", "رصيد المحفظة لا يكفي.")]

    def test_empty_candidate_falls_back_to_the_standard_message(self, error_app):
        error_app.secret_key = "test-secret"
        with error_app.test_request_context("/x"):
            flash_error(None)
            flashed = get_flashed_messages(with_categories=True)
        assert flashed == [("danger", standard_message(400))]


class TestServiceReturnedErrorsAreSanitized:
    """كل خدمة تُعيد (نتيجة، خطأ) والمسار يعرض ذلك الخطأ — فلا نص تقني فيه."""

    def test_rag_fallback_llm_failure_returns_a_safe_message(self, app):
        import app.services.rag_service as rag

        with app.app_context(), patch.object(rag, "_call_llm_with_context", side_effect=RuntimeError(SQL_LEAK)):
            result, err = rag._fallback_llm_query("سؤال", 1, 2)
        assert result is None
        assert err == standard_message(503)
        assert not looks_technical(err)

    def test_health_database_failure_message_is_sanitized(self, app):
        from app.services import health

        fake_db = MagicMock()
        fake_db.session.execute.side_effect = RuntimeError(SQL_LEAK)
        with app.app_context(), patch.object(health, "db", fake_db):
            result = health.check_database()
        assert result["status"] == "down"
        assert result["message"] == standard_message(503)
        assert not looks_technical(result["message"])

    def test_health_disk_failure_message_is_sanitized(self, app):
        from app.services import health

        with app.app_context(), patch("shutil.disk_usage", side_effect=OSError(SQL_LEAK)):
            result = health.check_disk()
        assert result["status"] == "down"
        assert not looks_technical(result["message"])

    def test_ai_grade_failure_dict_is_safe(self, app):
        """``{"error": str(e)}`` كان يُعادة للعميل مباشرة في /ai/grade/suggest."""
        import app.services.ai as ai_mod
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            svc.config.api_key = "sk-test-key"
            with (
                patch.object(ai_mod, "OPENAI_AVAILABLE", True),
                # حدود المعدّل مشتركة على مستوى الصنف — تُثبَّت ليكون الاختبار حتمياً
                patch.object(AiService, "_check_limits", return_value=(True, None)),
                patch.object(AiService, "_get_client", side_effect=RuntimeError(SQL_LEAK)),
            ):
                result = asyncio.run(svc.suggest_grade(student_answer="أ", question_type="essay", correct_answer="ب"))
        assert result["error"] == standard_message(503)
        assert result["error_code"] == "AI_GRADE_FAILED"
        assert result["fallback"]["score"] >= 5
        assert not looks_technical(json.dumps(result, ensure_ascii=False))

    def test_ai_generate_questions_failure_entry_is_safe(self, app):
        import app.services.ai as ai_mod
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            svc.config.api_key = "sk-test-key"
            with (
                patch.object(ai_mod, "OPENAI_AVAILABLE", True),
                patch.object(AiService, "_check_limits", return_value=(True, None)),
                patch.object(AiService, "_get_client", side_effect=RuntimeError(SQL_LEAK)),
            ):
                questions = asyncio.run(svc.generate_questions(topic="الكسور", count=2, user_id=1))
        first = questions[0]
        assert first["error"] == standard_message(503)
        assert not looks_technical(json.dumps(questions, ensure_ascii=False))

    def test_ai_stream_error_chunk_is_safe(self, app):
        """SSE منفذ تسريب كأي ردّ: التفصيل للسجل، والشاشة تأخذ رسالة آمنة."""
        import app.services.ai as ai_mod
        from app.services.ai import AiService
        from tests.conftest import _uid, make_user

        uid = make_user(app, role="student", email=f"d5-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            svc.config.api_key = "sk-test-key"

            async def _boom(*args, **kwargs):
                raise RuntimeError(SQL_LEAK)
                yield  # pragma: no cover — مولد لا يصل إليه التنفيذ

            with patch.object(ai_mod, "OPENAI_AVAILABLE", True), patch.object(svc, "_real_stream", _boom):
                chunks = _collect(svc.ask_question_stream(uid, "سؤال", class_id=None, lesson_id=None))

        error_lines = [c for c in chunks if '"error"' in c]
        assert error_lines
        # الرسالة داخل JSON مُرمَّزة (ensure_ascii) — نفكّها قبل المقارنة
        decoded = json.loads(error_lines[0][len("data: ") :].strip())
        assert decoded["error"] == standard_message(503)
        assert decoded["code"] == "AI_STREAM_FAILED"
        assert not looks_technical(json.dumps(decoded, ensure_ascii=False))
        assert chunks[-1] == "data: [DONE]\n\n"


class TestFlashRouteRendersSanitizedText:
    """اختبار من طرف إلى طرف: المسار → flash → الصفحة المعروضة للمستخدم.

    لا يكفي أن تكون الأداة المشتركة صحيحة؛ المطلوب أن الواجهة فعلاً لا تعرض
    الأثر التقني بعد مرور الاستثناء بخدمة تُعيد نصّه.
    """

    def test_technical_service_error_never_reaches_the_page(self, app, client):
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        admin_email = f"sanitize_admin{school_id}@t.com"
        make_user(app, role="school_admin", school_id=school_id, email=admin_email)
        teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

        with app.app_context():
            from app.models.user import UserRoleLink

            link_id = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first().id

        with (
            client,
            patch(
                "app.modules.school_approvals.routes.approve_user_role_link",
                return_value=(None, SQL_LEAK),
            ),
        ):
            client.post("/auth/login", data={"email": admin_email, "password": "TestPass123!"})
            resp = client.post(f"/school-admin/approvals/{link_id}/approve", follow_redirects=True)

        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        assert standard_message(400) in page
        for token in ("psycopg", "SELECT", "display_order", "does not exist"):
            assert token not in page


class TestNoRawExceptionTextInClientResponses:
    """حرس بنيوي (AST) — أين تُرسل رسالة الخطأ إلى المستخدم؟

    الفحص على شجرة الصياغة لا على النصّ: التوثيق والتعليقات تذكر النمط القديم
    بلا أن تكون منفذاً، والنصّ الخام قد يأتي بأشكال كثيرة. هنا نمسك الموضعين
    الوحيدين الذين يخرج منهما نصّ الخطأ إلى المستخدم:

      • ``flash(str(...))`` — تنبيه واجهة بنصّ الاستثناء الخام.
      • ``jsonify/json.dumps`` بمفتاح ``error``/``message`` قيمته ``str(...)``.

    الطريق الآمن هو ``flash_error`` / ``safe_message``، وهما يمرّان أولا على
    التنقية — فظهور النمطين أعلاه ثانية يعني فتح منفذ تسريب جديد.
    """

    _CLIENT_SINKS = ("flash", "jsonify", "dumps")
    _TEXT_KEYS = {"error", "message", "error_message", "detail", "details"}

    @staticmethod
    def _name(node: ast.AST) -> str | None:
        func = getattr(node, "func", None)
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @classmethod
    def _wraps_str_call(cls, node: ast.AST) -> bool:
        return any(isinstance(sub, ast.Call) and cls._name(sub) == "str" for sub in ast.walk(node))

    @classmethod
    def _offenders_in(cls, tree: ast.AST, path: str) -> list[str]:
        found: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = cls._name(node)
            if name not in cls._CLIENT_SINKS:
                continue
            if name == "flash":
                # نص التنبيه هو الوسيط الأول — أي ``str(...)`` فيه تسريب
                if any(cls._wraps_str_call(arg) for arg in node.args):
                    found.append(f"{path}:{node.lineno}")
            elif any(isinstance(arg, ast.Call) and cls._name(arg) == "str" for arg in node.args):
                # ``jsonify(str(e))`` مباشرةً — لا dict يحمل المفتاح
                found.append(f"{path}:{node.lineno}")
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Dict):
                    continue
                for key, value in zip(sub.keys, sub.values, strict=False):
                    if isinstance(key, ast.Constant) and key.value in cls._TEXT_KEYS and cls._wraps_str_call(value):
                        found.append(f"{path}:{sub.lineno}")
        return found

    def test_no_client_response_interpolates_a_raw_exception(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "app"
        offenders = [
            offender
            for path in root.rglob("*.py")
            for offender in self._offenders_in(ast.parse(path.read_text(encoding="utf-8")), str(path))
        ]
        assert offenders == []


def _collect(agen):
    """يجمع مخرجات مولد غير متزامن في قائمة (HTTP/SSE بلا شبكة)."""

    async def _run():
        return [chunk async for chunk in agen]

    return asyncio.run(_run())


# ═══════════════════════════════════════════════════════════════════════════
# التصنيف الدلالي (domain) — الواجهة تتصرف على نوع الخطأ لا على رمزه الخام
# ═══════════════════════════════════════════════════════════════════════════
class TestErrorDomain:
    """حقل domain يحمل نفس التدريل: إدخالات، جلسة، صلاحية، تعارض، حدود، عطل."""

    def test_domain_matches_the_taxonomy(self, app):
        cases = {
            400: "validation",
            401: "auth",
            403: "permission",
            404: "not_found",
            409: "conflict",
            429: "rate_limit",
            415: "validation",
            500: "server",
            502: "upstream",
            503: "upstream",
        }
        with app.app_context():
            for status, domain in cases.items():
                assert error_payload(status)["error"]["domain"] == domain, status
                assert error_domain(status) == domain, status

    def test_unmapped_status_falls_back_to_server(self, app):
        with app.app_context():
            assert error_domain(418) == "server"
            assert error_payload(418)["error"]["domain"] == "server"


class TestAllUserFacingCarryAnActionHint:
    """``standard_hint`` نقل الإجراء للنص: أياً كان مسار الرسالة، هناك خطوة تالية."""

    def test_every_catalogued_status_has_a_hint(self):
        from app.core.errors import _message_catalog

        for status in _message_catalog():
            hint = standard_hint(status)
            assert hint, status
            assert hint != standard_message(status), status  # التلميح إجراءٌ لا رسالة

    def test_html_error_page_shows_the_action_hint(self, error_app):
        resp = error_app.test_client().post("/adv-get-only", headers={"Accept": "text/html"})
        body = resp.get_data(as_text=True)
        assert resp.status_code == 405
        assert "ماذا تفعل الآن؟" in body
        assert "استخدم الأزرار داخل الواجهة لهذا الإجراء." in body

    def test_reinterpreted_code_keeps_its_own_hint(self):
        """CSRF رمزه 400 لكن حدثه انتهاء جلسة — تلميح «راجع المدخلات» مخالف له."""
        csrf_hint = hint_for("CSRF_FAILED", 400)
        assert csrf_hint != standard_hint(400)
        assert "حدّث الصفحة" in csrf_hint
        # التصنيفات التي لا تعيد التفسير تبقى على تلميح الرمز.
        assert hint_for("VALIDATION_ERROR", 400) == standard_hint(400)


class TestSafeDetails:
    """``details`` باب ثانٍ للنصوص — كان يمرّ كما هو؛ الآن نفس قاعدة التنقية."""

    def test_plain_scalars_pass_through(self, app):
        with app.app_context():
            details = error_payload(400, details={"field": "email", "received": 3, "ratio": 1.5, "ok": True})["error"][
                "details"
            ]
        assert details == {"field": "email", "received": 3, "ratio": 1.5, "ok": True}

    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "user_password",
            "auth_token",
            "secret",
            "credit_card_number",
            "auth",
            "session_cookie",
            "national_id",
        ],
    )
    def test_sensitive_keys_never_reach_the_client(self, app, key):
        with app.app_context():
            details = error_payload(400, details={key: "material-sec", "field": "email"})["error"]["details"]
        assert set(details) == {"field"}

    def test_technical_and_non_scalar_values_are_dropped(self, app):
        with app.app_context():
            details = error_payload(
                400,
                details={"cause": SQL_LEAK, "nested": {"a": 1}, "items": [1, 2], "missing": None, "field": "x"},
            )["error"]["details"]
        assert details == {"field": "x"}

    def test_overlong_strings_are_dropped(self, app):
        with app.app_context():
            details = error_payload(400, details={"note": "م" * 400, "field": "x"})["error"]["details"]
        assert details == {"field": "x"}

    def test_non_string_keys_are_skipped(self, app):
        with app.app_context():
            details = error_payload(400, details={1: "n", "field": "x"})["error"]["details"]
        assert details == {"field": "x"}

    def test_counts_are_capped_and_nondicts_are_emptied(self, app):
        with app.app_context():
            many = error_payload(400, details={f"k{i}": str(i) for i in range(15)})["error"]["details"]
            assert len(many) == 10
        assert safe_details("not-a-dict") == {}  # type: ignore[arg-type]
        assert safe_details(None) == {}  # type: ignore[arg-type]
