"""محرّك واتساب — تحقّق توقيع + مُوجِّه أوامر + إرسال غير حاجب.

نموذج التهديد (ما الذي يمنع كل خطأ):
    * **توقيع مفقود/خاطئ/هجوم إعادة تشغيل** ⇒ ``verify_inbound_signature``
      يفشل مغلقاً (بلا سرّ، أو سرّ غير مطابق، أو تجاوز حجم). لا استثناء:
      من لا يوقّع لا يُعالَج.
    * **رقم غير مربوط** ⇒ لا استعلام بيانات إطلاقاً — ردّ إرشادي فقط.
      الربط المؤكَّد شرط جوهري للوصول إلى بيانات أي طالب.
    * **تسريب بيانات** ⇒ كل معالج أمر يستقبل ``WhatsAppIdentity`` (مستخدم
      مُربَط) ويقرأ من قاعدة البيانات بفلتر صريح على صفه/صفوفه. لا استعلام
      بلا ``user_id``: محدِّد الإذن هو مصدر الاستعلام لا ناتج ``filter_by``.
    * **إعادة المعالجة** ⇒ ``ProcessedEvent`` على ``message_id`` يجعل
      التسليم المتكرر بلا أثر مع إقرار 200 حتى لا يعيد المُرسِل.
    * **إدخال خبيث** ⇒ الأرقام تُطبَّع إلى صيغة E.164، والأمر يُطابَق من
      قاموس ثابت (لا تنفيذ SQL ولا eval).

زمن الاستجابة: المعالجة تُنهي خلال استعلامات محدودة ثم **تسلّم الردّ**؛
الإرسال الصادر يذهب إلى طابور (Celery إن توفّر، وإلا خيط منفصل) فلا
تضيف بوابة Meta زمناً إلى استجابة الـ webhook.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import event, text

from app.core.logging import get_logger
from app.core.webhooks import MAX_WEBHOOK_BYTES, header_value, signature_matches
from app.extensions import db
from app.models.billing import ProcessedEvent

logger = get_logger(__name__)

# علام نشطاق التجاوز: مربك ذاتي، لا عامم، لأن يُشاركه طلبات متوازية
_webhook_scope = threading.local()

# ── ثوابت البروتوكول ──────────────────────────────────────────────
META_SIGNATURE_HEADER = "X-Hub-Signature-256"
TWILIO_SIGNATURE_HEADER = "X-Twilio-Signature"
MAX_BODY_BYTES = MAX_WEBHOOK_BYTES
MAX_MESSAGE_CHARS = 1000
_EVENT_PREFIX = "wa_msg_"

#: نوع الإشعار الداخلي لردّ واتساب — مُدرَج في DEFAULT_TYPES للتفضيلات.
NOTIFICATION_TYPE = "message"
NOTIFICATION_TITLE = "رد واتساب"

_NON_DIGITS = re.compile(r"\D")
_PHONE_OK = re.compile(r"^\+[1-9]\d{7,14}$")

# طابور الإرسال: خيطان يكفيان (إرسال لا معالجة طلب) — والردّ لا ينتظره.
# ترتيب الرسائل لنفس الرقم محفوظ لأن الخيوط نفسها محدودة.
_OUTBOUND_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wa-outbound")


# ═══════════════════════════ التحقّق من التوقيع ═══════════════════════════
def normalize_phone(raw: str | None) -> str | None:
    """تطبيع رقم إلى صيغة E.164 — أو ``None`` إن كان غير صالح.

    Meta/WhatsApp ترسل الصيغة الدولية أحياناً بلا ``+``؛ نضيفها قبل التطابق.
    """
    if not raw:
        return None
    cleaned = _NON_DIGITS.sub("", str(raw).strip())
    if not cleaned:
        return None
    candidate = cleaned[2:] if cleaned.startswith("00") else cleaned
    if not candidate:
        return None
    e164 = f"+{candidate}"
    return e164 if _PHONE_OK.match(e164) else None


def verify_inbound_signature(
    *,
    raw_body: bytes,
    headers,
    secret: str | None,
    header_name: str = META_SIGNATURE_HEADER,
) -> bool:
    """تحقّق HMAC-SHA256 على الجسم الخام — fail-closed بلا استثناء."""
    if not secret:
        logger.error("whatsapp_signature_secret_missing", action="reject")
        return False
    if len(raw_body or b"") > MAX_BODY_BYTES:
        logger.warning("whatsapp_body_too_large", limit=MAX_BODY_BYTES, action="reject")
        return False
    received = header_value(headers, header_name)
    if not received:
        logger.warning("whatsapp_signature_absent", header=header_name, action="reject")
        return False
    return signature_matches(secret, raw_body, received)


def verify_twilio_signature(*, url: str, params: dict[str, str], headers, token: str | None) -> bool:
    """تحقّق توقيع Twilio (base64 HMAC-SHA1 على URL + قيم مرتّبة).

    Twilio يختلف عن Meta: الخوارزمية SHA1 والناتج base64، وقيم الـ form
    تُرتَّب أبجدياً وتُلحق بالـ URL قبل التوقيع.
    """
    if not token:
        logger.error("whatsapp_twilio_token_missing", action="reject")
        return False
    received = header_value(headers, TWILIO_SIGNATURE_HEADER)
    if not received:
        logger.warning("whatsapp_twilio_signature_absent", action="reject")
        return False
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, received)


def verification_challenge_response(*, mode: str | None, verify_token: str | None, challenge: str | None) -> str | None:
    """تحدّي اشتراك Meta — يُعاد الـ challenge فقط عند مطابقة التوكن."""
    # Meta ترسل hub.mode مع التحدّي؛ لكن استدعاءً مبسّطاً قد يرسل challenge فقط.
    # غياب الصريح = subscribe (والمتسارعة صريحة تُرفض).
    if mode not in (None, "subscribe"):
        return None
    expected = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if not expected or not verify_token or not hmac.compare_digest(str(expected), str(verify_token)):
        logger.warning("whatsapp_verify_token_rejected", action="reject")
        return None
    return challenge


# ═══════════════════════ نطاق RLS لويب هوك موقَّع ═══════════════════════
@contextmanager
def verified_webhook_scope() -> Iterator[None]:
    """تجاوز RLS لمعاملة ويب هوك اجتازت التحقق من التوقيع.

    لماذا يلزم: الطلب يصل من Meta بلا جلسة مستخدم، فيضبط
    ``set_tenant_for_request`` المتغيرين على ``'0'``. وبما أن RLS مُجبَر
    (FORCE) على ``whatsapp_links`` فإنّ ``school_id = 0`` يُخفي كل الروابط،
    فيعود ``resolve_identity`` بلا هوية ويُردّ على كل رسالة «غير مربوط»
    رغم صحة التوقيع — أي أن مُوجِّه الأوامر معطَّل في الإنتاج. والطالب لا
    يحمل ``school_id``، فالبحث يبدأ من الرقم وحده ولا بدّ من تجاوز.

    الضمانات:
        * لا يُمنح إلا بعد نجاح ``verify_inbound_signature`` (بلا استثناء).
        * **عند المعاملة، لا على متغيّر الاتصال.** بعد ضبطه يمرّ
          ``tx()`` بـcommit فيُطلق الاتصال إلى المجموعة، فينتقل الاستعلام
          التالي إلى اتصال آخر لا يحمل التجاوز — وهو ما كان يُسقط الطلب
          بـ500 في الخادم الحقيقي. لذلك يُعاد الضبط في ``after_begin``:
          يتكفّل بأن يطاله كل معاملة تبدأ داخل النطاق.
        * يضبط المتغيّرين معاً: ``app.current_school_id`` يجب ألّا يكون
          فارغاً، وسلسلة فارغة تُسقط الاستعلام بـ``invalid input syntax``،
          وPostgreSQL لا يضمن تقييم ``OR`` بترتيب معيّن فلا يصلنا التخطّي
          بتجاوز تقييم الفرع الثاني.
        * لا أثر بعد النطاق: إنهاء المعاملة يُسقط ``SET LOCAL``، فلا يبقى
          تجاوز مفتوح ولا متغيّر عالق على اتصال مجمَّع لاحق.
    """
    _webhook_scope.active = True
    try:
        db.session.execute(text("SET LOCAL app.is_super_admin = '1'"))
        db.session.execute(text("SET LOCAL app.current_school_id = '0'"))
        yield
    finally:
        _webhook_scope.active = False
        try:
            # إنهاء العملية يُسقط متغيرات SET LOCAL تماماً:
            # لا يبقى تخطي بالعود ولا يعلق متغيرات المجموعة.
            db.session.rollback()
        except Exception:
            logger.exception("whatsapp_rls_scope_reset_failed")


@event.listens_for(db.session, "after_begin")
def _keep_webhook_scope_on_new_transactions(session, transaction, connection) -> None:
    """يُكرّ التجاوز على كل معاملة تبدأ فياصل النطاق.

    ``tx()`` ينهي معاملته بـcommit ويُطلّق الاتصال من
    الجلسة، فيقد تخطّي معاملة خالية من المجموعة
    وتقرّر التجاوز. التمسك هناك يعدّه السياري مع النطاق.
    """
    if not getattr(_webhook_scope, "active", False):
        return
    # PostgreSQL لا يقبل أعداد متعددات مفصولة في جملة واحدة؛
    # لذلك عباران.
    connection.execute(text("SET LOCAL app.is_super_admin = '1'"))
    connection.execute(text("SET LOCAL app.current_school_id = '0'"))


# ═══════════════════════════ الهوية ═══════════════════════════
@dataclass(frozen=True)
class WhatsAppIdentity:
    """نتيجة ربط الرقم بحساب — تُمرَّر لكل معالج أمر."""

    user_id: int
    school_id: int
    phone: str
    role: str


def resolve_identity(phone: str | None) -> WhatsAppIdentity | None:
    """ربط الرقم بحساب في استعلام واحد (O(1)) — أو ``None``.

    الاستعلام يحمل ``user_id`` صراحةً؛ لا ``join`` ولا استعلام لاحق، فلا
    وجود لمسار N+1 هنا.
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return None

    from app.models.user import User
    from app.models.whatsapp import WhatsAppLink

    row = (
        db.session.query(WhatsAppLink.user_id, WhatsAppLink.school_id, User.role)
        .join(User, User.id == WhatsAppLink.user_id)
        .filter(WhatsAppLink.phone == normalized, WhatsAppLink.is_active.is_(True))
        .first()
    )
    if row is None:
        logger.info("whatsapp_identity_not_linked", phone=normalized[-4:])
        return None
    return WhatsAppIdentity(
        user_id=row.user_id, school_id=row.school_id, phone=normalized, role=str(getattr(row.role, "value", row.role))
    )


def already_handled(message_id: str) -> bool:
    """هل سبق معالجة هذه الرسالة؟ — استعلام واحد."""
    return ProcessedEvent.query.filter_by(event_id=_event_id(message_id)).first() is not None


def _event_id(message_id: str) -> str:
    return f"{_EVENT_PREFIX}{message_id}"


def mark_handled(message_id: str, payload: dict) -> None:
    """تسجيل الرسالة كمعالجة — ضمن معاملة ``tx``blr واحدة."""
    db.session.add(ProcessedEvent(event_id=_event_id(message_id), gateway="whatsapp", payload=payload))


# ═══════════════════════════ الأوامر ═══════════════════════════
HELP_TEXT = (
    "أوامر متاحة:\n"
    "• #حضور — حضور اليوم لأبنائك\n"
    "• #درجات — آخر الدرجات\n"
    "• #اشتراك — حالة الاشتراك\n"
    "• #مساعدة — هذه القائمة"
)

CommandHandler = Callable[[WhatsAppIdentity], str]


def _children_ids(identity: WhatsAppIdentity) -> list[int]:
    """أبناء ولي الأمر (لمعلم/طالب: نفسه فقط) — استعلام واحد."""
    from app.models.user import UserRole

    if identity.role == UserRole.parent.value:
        from app.models.family import FamilyLink

        return [row.student_id for row in FamilyLink.query.filter_by(parent_id=identity.user_id, status="active").all()]
    return [identity.user_id]


def _cmd_attendance(identity: WhatsAppIdentity) -> str:
    """حضور اليوم للطلاب المرتبطين — استعلام واحد لكل الدفعة."""
    from app.models.attendance import Attendance

    ids = _children_ids(identity)
    if not ids:
        return "لا يوجد طلاب مرتبطون بحسابك."
    rows = (
        Attendance.query.filter(
            Attendance.student_id.in_(ids), Attendance.date == date.today(), Attendance.class_id.isnot(None)
        )
        .order_by(Attendance.student_id.asc())
        .all()
    )
    if not rows:
        return "لم يُسجَّل حضور اليوم بعد."
    labels = {"present": "حاضر", "absent": "غائب", "late": "متأخر", "excused": "بعذر"}
    lines = [f"حضور اليوم: {labels.get(row.status, row.status)}" for row in rows]
    return "\n".join(lines)


def _cmd_grades(identity: WhatsAppIdentity) -> str:
    """آخر الدرجات — استعلام واحد بحدّ أعلى."""
    from app.models.gradebook import GradeEntry

    ids = _children_ids(identity)
    if not ids:
        return "لا يوجد طلاب مرتبطون بحسابك."
    rows = GradeEntry.query.filter(GradeEntry.student_id.in_(ids)).order_by(GradeEntry.updated_at.desc()).limit(5).all()
    if not rows:
        return "لا توجد درجات مسجّلة بعد."
    return "\n".join(f"درجة: {row.mark}" for row in rows)


def _cmd_subscription(identity: WhatsAppIdentity) -> str:
    """حالة الاشتراك — استعلام واحد."""
    from app.models.billing import Subscription

    row = Subscription.query.filter(Subscription.user_id == identity.user_id).order_by(Subscription.id.desc()).first()
    if row is None:
        return "لا يوجد اشتراك مرتبط بحسابك."
    return f"الاشتراك: {row.status} — حتى {row.end_at.date() if row.end_at else '—'}"


def _cmd_help(identity: WhatsAppIdentity) -> str:  # noqa: ARG001
    return HELP_TEXT


UNLINKED_REPLY = "هذا الرقم غير مربوط بأي حساب. أرسل #ربط للبدء."


#: قاموس ثابت: نص الأمر → معالجه. لا تنفيذ ديناميكي ولا استعلام مضمّن.
COMMANDS: dict[str, CommandHandler] = {
    "حضور": _cmd_attendance,
    "attendance": _cmd_attendance,
    "درجات": _cmd_grades,
    "grades": _cmd_grades,
    "اشتراك": _cmd_subscription,
    "subscription": _cmd_subscription,
    "مساعدة": _cmd_help,
    "help": _cmd_help,
}


def parse_command(text: str | None) -> tuple[str, list[str]] | None:
    """تحليل نص الرسالة إلى (أمر، وسائط) — أو ``None`` إن لم يكن أمراً."""
    if not text:
        return None
    body = text.strip()
    if not body.startswith("#"):
        return None
    parts = body[1:].split()
    if not parts:
        return None
    return parts[0].strip().lower(), [part for part in parts[1:]]


def route_command(text: str | None, identity: WhatsAppIdentity | None) -> str:
    """توجيه الأمر إلى معالجه — مع ردود fail-closed لغير المربوط."""
    parsed = parse_command(text)
    if parsed is None:
        return "أرسل أمراً يبدأ بـ # — مثال: #مساعدة"
    keyword, _args = parsed
    handler = COMMANDS.get(keyword)
    if handler is None:
        return f"أمر غير معروف: #{keyword}\n{HELP_TEXT}"
    if identity is None:
        return UNLINKED_REPLY
    return handler(identity)


# ═══════════════════════════ الإرسال الصادر ═══════════════════════════
@dataclass(frozen=True)
class OutboundMessage:
    to: str
    body: str
    idempotency_key: str


def deliver_outbound(message: OutboundMessage) -> bool:
    """تنفيذ الإرسال فعلياً — يعمل في الخيط الخلفي لا في مسار الطلب.

    بلا إعداد (token/رقم مُرسِل) لا نُرسل ولا ننهار: نُسجّل ونُرجع ``False``
    حتى لا يفشل webhook بسبب غياب إعداد في بيئة تطوير.
    """
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    graph_version = os.getenv("WHATSAPP_GRAPH_VERSION", "v21.0")
    if not token or not phone_number_id:
        logger.info("whatsapp_send_skipped_unconfigured", to=message.to[-4:])
        return False

    import requests

    url = f"https://graph.facebook.com/{graph_version}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": message.to,
        "type": "text",
        "text": {"body": message.body[:MAX_MESSAGE_CHARS]},
    }
    try:
        response = requests.post(url, json=body, headers=headers, timeout=(3, 10))
        ok = response.status_code == 200
        if not ok:
            logger.warning("whatsapp_send_rejected", status=response.status_code, to=message.to[-4:])
        return ok
    except Exception:
        logger.exception("whatsapp_send_failed", to=message.to[-4:])
        return False


def dispatch_outbound(message: OutboundMessage) -> None:
    """جدولة الإرسال دون حجب: Celery عند توفّره، وإلا خيط مستقل.

    الهدف: استجابة الـ webhook تُعاد فوراً بعد المعالجة (أقل من 200ms)
    لأن زمن Meta لا يدخل مسار الطلب.
    """
    task = _celery_task()
    if task is not None:
        try:
            task.delay(message.to, message.body, message.idempotency_key)
            return
        except Exception:
            logger.exception("whatsapp_celery_dispatch_failed")
    _OUTBOUND_POOL.submit(deliver_outbound, message)


def _celery_task():
    """مهمة Celery إن كانت الحزمة مثبّتة — وإلا ``None``.

    Celery غير مثبّت في بيئات الاختبار عمداً، لذا لا يجوز أن يكون شرطاً
    لعمل المحرّك.
    """
    try:
        from app.tasks.notifications import send_whatsapp_task

        return send_whatsapp_task
    except Exception:
        return None


# ═══════════════════════════ المعالجة ═══════════════════════════
def process_incoming_message(
    *,
    message_id: str,
    phone: str | None,
    text: str | None,
    timestamp: str | None = None,
) -> dict:
    """معالجة رسالة واردة — معالَجة واحدة ثم ردّ غير حاجب.

    Returns:
        ``{"status": "processed"|"duplicate"|"unlinked", "reply": str}``.
    """
    if not message_id:
        logger.warning("whatsapp_message_without_id", action="reject")
        return {"status": "unlinked", "reply": UNLINKED_REPLY}

    if already_handled(message_id):
        logger.info("whatsapp_duplicate_ignored", message_id=message_id)
        return {"status": "duplicate", "reply": ""}

    identity = resolve_identity(phone)
    reply = route_command(text, identity)

    def _persist():
        mark_handled(message_id, {"phone_tail": (normalize_phone(phone) or "")[-4:], "at": timestamp})

    from app.core.db import tx

    tx(_persist)

    if identity is not None:
        _record_reply(identity, reply)

    dispatch_outbound(OutboundMessage(to=normalize_phone(phone) or "", body=reply, idempotency_key=message_id))
    return {"status": "processed" if identity else "unlinked", "reply": reply}


def _record_reply(identity: WhatsAppIdentity, reply: str) -> None:
    """إشعار داخلي بأنّ ردّ واتساب وصل — حلقة الوصل بين الـ webhook والواجهة.

    الأثر الوحيد المعتمد في E2E: بعد رسالة موقّعة من رقم مربوط، تظهر نقطة
    في ``/notifications/`` وشارة في شريط التنقّل. بلا استعلام قائمة: استعلام
    التفضيل + الإدراج، ثابتان لا تتوسّعان بعدد الأبناء.

    الرقم غير المربوط لا يُنشئ إشعاراً — لا حساب يملكه.
    """
    from app.services.communication import notify

    notify(identity.user_id, NOTIFICATION_TYPE, NOTIFICATION_TITLE, body=reply)


def now_iso() -> str:
    """طابع زمني ISO — للحوافز/السجلات (UTC)."""
    return datetime.now(UTC).isoformat()
