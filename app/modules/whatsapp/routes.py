"""مسارات ويب هوك واتساب — بوابة الدخول الوحيدة للرسائل الخارجية.

الاستجابة سريعة عمداً: التحقق + استعلامات محدودة + ردّ فوري، والإرسال
الصادر في طابور. الهدف < 200ms زمن استجابة حتى لا يعيد مزوّد الخدمة الإرسال.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.webhooks import safe_json_loads
from app.services.whatsapp import (
    MAX_BODY_BYTES,
    META_SIGNATURE_HEADER,
    process_incoming_message,
    verification_challenge_response,
    verified_webhook_scope,
    verify_inbound_signature,
)
from flask import abort, current_app, jsonify, request

from . import bp

logger = get_logger(__name__)


@bp.get("/webhook")
@bp.post("/webhook")
def whatsapp_webhook():
    """VERIFY challenge (GET/POST) + استقبال الأحداث (POST).

    لا يُكشف أي سبب داخلي للفشل: الردّ 403/401 بلا تفاصيل، والسبب في السجل.
    """
    mode = request.args.get("hub.mode")
    verify_token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode or challenge:
        response = verification_challenge_response(mode=mode, verify_token=verify_token, challenge=challenge)
        if response is None:
            abort(403)
        return response, 200

    raw_body = request.get_data()
    if len(raw_body) > MAX_BODY_BYTES:
        logger.warning("whatsapp_webhook_body_too_large", size=len(raw_body))
        abort(413)

    secret = current_app.config.get("WHATSAPP_APP_SECRET") or None
    if not verify_inbound_signature(
        raw_body=raw_body,
        headers=dict(request.headers),
        secret=secret,
        header_name=META_SIGNATURE_HEADER,
    ):
        logger.warning("whatsapp_webhook_signature_rejected", path=request.path)
        abort(401)

    payload = safe_json_loads(raw_body)
    # بعد التوقيع فقط: تجاوز RLS يُمنح لهذه المعاملة ويُسحب بعدها.
    with verified_webhook_scope():
        results = _handle_events(payload)
    return jsonify({"status": "processed", "handled": results}), 200


def _handle_events(payload: dict[str, Any]) -> int:
    """تفكيك حمولة Meta وتنفيذ كل رسالة واردة — عدد الرسائل المُعالَجة."""
    handled = 0
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue
            for message in value.get("messages", []) or []:
                if not isinstance(message, dict):
                    continue
                outcome = process_incoming_message(
                    message_id=str(message.get("id", "")),
                    phone=(message.get("from") or None),
                    text=_message_text(message),
                    timestamp=None,
                )
                logger.info("whatsapp_message_handled", status=outcome["status"])
                handled += 1
    return handled


def _message_text(message: dict[str, Any]) -> str | None:
    """نص الرسالة — يدعم ``text`` والرسائل التفاعلية (``button``/``list``)."""
    text = message.get("text")
    if isinstance(text, dict):
        body = text.get("body")
        if isinstance(body, str):
            return body
    button = message.get("button")
    if isinstance(button, dict) and isinstance(button.get("text"), str):
        return button["text"]
    interactive = message.get("interactive")
    if isinstance(interactive, dict):
        for key in ("button_reply", "list_reply"):
            reply = interactive.get(key)
            if isinstance(reply, dict) and isinstance(reply.get("title"), str):
                return reply["title"]
    return None
