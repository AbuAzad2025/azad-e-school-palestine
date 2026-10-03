"""تحقّق توقيعات Webhook — أساس مشترك لكل البوابات.

المبادئ (fail-closed):
    1. **لا سر ⇒ رفض.** غياب المفتاح يعني رفضاً صريحاً لا تجاوزاً صامتاً.
    2. **مقارنة ثابتة الزمن** دائماً (``hmac.compare_digest``) — لا ``==`` ولا
       ``in``: المقارنة بايت-ببايت تكشف موضع أول اختلاف عبر زمن التنفيذ.
    3. **الجسم الخام هو ما وقّع عليه المرسِل.** إعادة ترميز JSON المفكوك
       تُنتج بايتات قد تختلف عن المُرسَل (ترتيب المفاتيح، المسافات، تهريب
       يونيكود، الأرقام العشرية) فتفشل مصادقة مشروع legit. لذلك نوقّع على
       ``request.get_data()`` كما هو، ونسقط للـ JSON canonico فقط حين لا
       يتوفّر الجسم الخام (مستدعون بلا سياق طلب).
    4. **لا تسرّب معلومات:** لا نُرجع أي جزء من السر أو التوقيع المتوقع.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# بادئة شائعة في الترويسات: "sha256=<hex>"
_ALGORITHM_PREFIX = "sha256="

# سقف حجم الجسم قبل التوقيع: حمولة webhook أكبر من ذلك رفضتُها مشبوهة،
# وتحميلها كلها في الذاكرة غير ضروري (المسار يفشل قبل أي كتابة).
MAX_WEBHOOK_BYTES = 256 * 1024


def header_value(headers: Mapping[str, Any] | None, name: str) -> str:
    """قراءة ترويسة بطريقة غير حساسة لحالة الأحرف (وآمنة مع dict العادي).

    ``dict(request.headers)`` يحفظ حالة الأحرف كما أرسلها المرسِل، فمفتاح
    مصغَّر (``x-paytabs-signature``) كان يُفقد التوقيع بصمت.
    """
    if not headers:
        return ""
    wanted = name.strip().lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.strip().lower() == wanted:
            return "" if value is None else str(value).strip()
    return ""


def canonical_payload_bytes(payload: Any) -> bytes:
    """تمثيل JSON حتمي للـ payload — مسار احتياطي حين لا يتوفّر الجسم الخام.

    الفواصل هنا مطابقة لـ ``json.dumps(payload, sort_keys=True)`` عمداً: هذه
    هي البايتات التي وقّع عليها المستدعون السابقون قبل إدخال الجسم الخام،
    وتغييرها كان سيُسقط توقيعات التكاملات القائمة.
    """
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")


def safe_json_loads(raw: bytes | str) -> dict[str, Any]:
    """فك JSON إلى dict — يرجع ``{}`` عند الفشل بدل رفع استثناء غير معالَج."""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("webhook_body_not_json")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def signing_body(raw_body: bytes | None, payload: Any) -> bytes:
    """الجسم الذي نوقّع عليه: الخام إن وُجد، وإلا JSON حتمي."""
    if isinstance(raw_body, (bytes, bytearray)) and raw_body:
        return bytes(raw_body)
    return canonical_payload_bytes(payload)


def _normalize_signature(value: str) -> str:
    """تجريد بادئة الخوارزمية — بعض المرسلين يضعون ``sha256=``."""
    text = value.strip()
    if text.lower().startswith(_ALGORITHM_PREFIX):
        return text[len(_ALGORITHM_PREFIX) :]
    return text


def signature_matches(secret: str | None, body: bytes, received_signature: str) -> bool:
    """مقارنة ثابتة الزمن لتوقيع HMAC-SHA256 — ``False`` في كل حالات الفشل."""
    if not secret:
        logger.error("webhook_signature_secret_missing", action="reject")
        return False
    received = _normalize_signature(received_signature or "")
    if not received:
        logger.warning("webhook_signature_missing", action="reject")
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


def verify_hmac_webhook(
    *,
    secret: str | None,
    headers: Mapping[str, Any] | None,
    header_name: str,
    raw_body: bytes | None,
    payload: Any,
    gateway: str,
) -> bool:
    """تحقّق توقيع HMAC-SHA256 من ترويسة محددة — fail-closed بالكامل.

    Returns:
        ``True`` فقط عند تطابق توقيع ثابت الزمن على الجسم الموقَّع.
    """
    if len(raw_body or b"") > MAX_WEBHOOK_BYTES:
        logger.warning("webhook_body_too_large", gateway=gateway, limit=MAX_WEBHOOK_BYTES, action="reject")
        return False

    received = header_value(headers, header_name)
    if not received:
        logger.warning("webhook_signature_header_absent", gateway=gateway, header=header_name, action="reject")
        return False

    body = signing_body(raw_body, payload)
    ok = signature_matches(secret, body, received)
    if not ok:
        logger.warning("webhook_signature_mismatch", gateway=gateway, header=header_name, action="reject")
    return ok


__all__ = [
    "MAX_WEBHOOK_BYTES",
    "canonical_payload_bytes",
    "header_value",
    "safe_json_loads",
    "signature_matches",
    "signing_body",
    "verify_hmac_webhook",
]
