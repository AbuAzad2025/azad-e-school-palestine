"""معالجة الأخطاء المركزية — رسائل آمنة، تنسيق واحد، ومعرّف متابعة.

ما تحلّه هذه الوحدة: كانت الاستجابات تخرج بأنماط مختلفة (قالب HTML في مسار،
JSON في آخر، وصفحة Werkzeug الإنجليزية في ثالث)، وكان استثناء غير متوقع في
مسار API يعطي قالب HTML. هنا نقطة واحدة تحكم كل ذلك:

  • تنسيق JSON واحد لكل أخطاء الـ API — نفس شكل ``app/core/api.api_error``
    (الاثنان يبنيان على ``error_payload`` نفسه، فلا يختلف الشكل بين مسارين).
  • تنقية كل نص قبل عرضه: أي أثر SQL/محرّك/مسار ملف/كائن بايثون يُستبدل برسالة
    عربية معيارية قابلة للتنفيذ — لا تفصيل تقني يصل للمستخدم أبداً.
  • التفاصيل الكاملة تُسجَّل على الخادم فقط، ويُعاد للمستخدم معرّف ارتباط
    واحد يربط ما رآه بما في السجل، بلا كشف أي شيء عنه.
"""

from __future__ import annotations

import re
from typing import Any

from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from app.core.i18n import _
from app.core.logging import get_correlation_id, get_logger

logger = get_logger(__name__)

API_VERSION = "v1"

# رمز SQLSTATE لانتهاك القيد الفريد — الفرق بين «تعارض يفهمه المستخدم»
# و«عطل برمجي» في قيود النزاهة (انظر map_exception).
_UNIQUE_VIOLATION = "23505"


def _message_catalog() -> dict[int, str]:
    """الرسائل المعيارية — المصدر الوحيد لكل نص خطأ يظهر للمستخدم.

    دالة لا ثابتاً، ولسببين معاً: مستخرِج Babel يرى النص فقط حين يكون
    وسيطاً حرفياً داخل ``_()`` (قاموس نصّي يخرج بلا ترجمة إنجليزية)، ولو
    نُودي ``_()`` عند الاستيراد لتجمّدت الترجمة على لغة لحظة الاستيراد.
    """
    return {
        400: _("الطلب غير صالح. تحقّق من البيانات المُرسلة ثم حاول مجدداً."),
        401: _("انتهت جلستك أو لم تسجّل الدخول. يرجى تسجيل الدخول للمتابعة."),
        403: _("لا تملك صلاحية الوصول إلى هذا المورد."),
        404: _("المورد المطلوب غير موجود أو تم نقله."),
        405: _("هذا الإجراء غير مدعوم في هذا العنوان. يرجى العودة والاستخدام من الواجهة."),
        409: _("لا يمكن إتمام العملية بسبب تعارض في البيانات. حدّث الصفحة ثم حاول مجدداً."),
        413: _("حجم الملف المرسل أكبر من الحد المسموح."),
        415: _("نوع الملف غير مدعوم. استخدم صيغة مدرجة في دليل المنصة."),
        422: _("البيانات المُرسلة غير مكتملة أو غير صحيحة."),
        # خدمة خارجية (AI/بوابة دفع): عطل مؤقت — الرسالة هنا أوضح وأدقّ من 500
        502: _("تعذّر إكمال الطلب من خدمة خارجية. يرجى المحاولة بعد قليل."),
        429: _("عدد الطلبات كبير خلال وقت قصير. يرجى المحاولة بعد قليل."),
        500: _("حدث خطأ غير متوقع في الخادم. تم تسجيل التفاصيل وسيتابعها الفريق."),
        503: _("الخدمة غير متاحة مؤقتاً. يرجى المحاولة بعد قليل."),
    }


STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}

# ─── تصنيف دلالي (domain) — خاصية مُضافة للـ JSON فقط، بلا تغيير الرموز ──
# يحدد الواجهة الطرفية (toast/صفحة خطأ) ما هو الحدث: مدخلات تحتاج تصحيح،
# جلسة/صلاحية، حالة تعارض، محاولات كثيرة، خدمة منكسرة، أم عطل داخلي حقيقي.
# ملاحظة مقصودة: التصنيف هنا للتوجيه والإدراك (filtering/reacting)، لا
# للاستدلال داخل منطق العمل — استدلال منطق العمل يبقى في استثناءاته الخاصة.
ERROR_DOMAINS: dict[int, str] = {
    400: "validation",  # مدخلات المستخدم — يمكنه تصحيحها
    401: "auth",  # جلسة منتهية/غير مسجّل — سجّل الدخول
    403: "permission",  # مسجّل لكن لا صلاحية — يلجأ للإدارة
    404: "not_found",  # مورد غير موجود — يتحقق من الرابط
    405: "validation",  # استخدام طريقة خاطئة على عنوان — من الواجهة
    409: "conflict",  # التعارض/حالة متغيّرة — حدّث ثم أعد
    413: "validation",  # ملف أكبر من الحد — قلّص
    415: "validation",  # صيغة غير مدعومة — صيغة أخرى
    422: "validation",  # بيانات غير مكتملة/غير صحيحة — صحّح الحقول
    429: "rate_limit",  # محاولات كثيرة — انتظر
    500: "server",  # عطل داخلي حقيقي — للفريق
    502: "upstream",  # خدمة خارجية (AI/دفع) منكسرة
    503: "upstream",  # بنية تحتية غير متاحة مؤقتاً — أعد المحاولة
}

# المفاتيح المحظورة من تفاصيل الأخطاء — أي مفتاح يوحي بمصادقة/دفع/هوية يُسقط
# حتى لو قيمته نظيفة: تفاصيل الـ details شكل مساعِد للعميل، لا مستند بيانات.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:passw(?:or)?d|passwd|secret|token|auth(?:orization)?|cookie|otp|\bpin\b|cvv|card|iban|international_identif|national_id|id_number)",
    re.IGNORECASE,
)

# ─── أنماط الأثر التقني: ممنوعة من الوصول إلى المستخدم ─────────────────
# تُطبَّق على أي نص قبل عرضه: رسالة خدمة، وصف استثناء، نص قيد قاعدة بيانات.
_TECHNICAL_LEAK_RE = re.compile(
    r"("
    r"psycopg|sqlalchemy|asyncpg|pg8000|"
    r"integrityerror|operationalerror|programmingerror|dataerror|"
    r"databaseerror|interfaceerror|uniqueviolation|foreignkeyviolation|"
    r"notnullviolation|checkviolation|invalidtextrepresentation|"
    r"select\s+[^;]{0,200}\sfrom\s|insert\s+into\s|update\s+\w+\s+set\s|delete\s+from\s|"
    r"traceback\s+\(most\s+recent\s+call\s+last\)|"
    r"file\s+\"[^\"]*\"|line\s+\d+\s*,|"
    r"duplicate\s+key|violates\s+\w+\s+constraint|"
    r"relation\s+\"[^\"]*\"\s+does\s+not\s+exist|"
    r"column\s+\"[^\"]*\"\s+does\s+not\s+exist|"
    r"new\s+row\s+violates|"
    r"<class\s+'|<[a-z_.]+\s+object\s+at\s+0x"
    r")",
    re.IGNORECASE,
)

# ─── القوالب: كل رمز معروف له صفحته المصمّمة، والباقي قالب عام صريح ─────
_HTML_TEMPLATES: dict[int, str] = {
    403: "errors/403.html",
    404: "errors/404.html",
    429: "errors/429.html",
    500: "errors/500.html",
}

_GENERIC_TEMPLATE = "errors/generic.html"


def standard_message(status: int) -> str:
    """الرسالة المعيارية للرمز بلغة الطلب الحالية (ar/en).

    يُبنى الكتالوج عند الطلب لا عند الاستيراد، فترجمة الردّ تتبع لغة الطلب.
    """
    catalog = _message_catalog()
    return catalog.get(status) or catalog[500]


def _hint_catalog() -> dict[int, str]:
    """الخطوة التالية للمستخدم لكل رمز — عين الصدارة لكل شيء آخر.

    الرسالة توضّح ماذا حدث، والتلميح يقول ماذا يفعل الآن. هذه هي المسافة
    بين رسالة خطأ تقنية ورسالة صديقة للمستخدم: إجراء قابل للتنفيذ، بلغة
    المستخدم، بلا عداوة ولا تفصيل داخلي.
    """
    return {
        400: _("راجع البيانات المدخلة ثم أعد الإرسال."),
        401: _("سجّل الدخول من جديد ثم أعد المحاولة."),
        403: _("إن كنت ترى أن هذا خطأ، تواصل مع إدارة مدرستك لتفعيل صلاحيتك."),
        404: _("تحقق من الرابط أو عد إلى لوحتك الرئيسية."),
        405: _("استخدم الأزرار داخل الواجهة لهذا الإجراء."),
        409: _("حدّث الصفحة لتصلك أحدث البيانات ثم أعد المحاولة."),
        413: _("قلّص حجم الملف ثم أعد المحاولة."),
        415: _("استخدم صيغة ملف مدرجة في دليل المنصة."),
        422: _("صحّح الحقول المشار إليها ثم أعد الإرسال."),
        429: _("انتظر دقيقة أو دقيقتين ثم أعد المحاولة."),
        500: _("إن تكرر الخطأ، تواصل مع الدعم وأرسل لهم رقم المتابعة."),
        502: _("أعد المحاولة بعد دقائق؛ الخدمة تعمل على استعادتها."),
        503: _("أعد المحاولة بعد دقائق؛ الخدمة تتعرض لضغط مؤقت."),
    }


def standard_hint(status: int) -> str:
    """الخطوة التالية المقترحة للرمز بلغة الطلب — تُعرض في الصفحة والـ flash."""
    catalog = _hint_catalog()
    return catalog.get(status) or catalog[500]


def hint_for(code: str | None, status: int) -> str:
    """التلميح النهائي للردّ — يميّز التصنيف المُعاد تفسيره عن الرمز الخام.

    CSRFError رمزه 400 لكن حدثه انتهاء جلسة: تلميح «راجع البيانات المدخلة»
    تلميح مخالف للحدث، لذا التصنيف الذي يعيد تفسير الرمز (``CSRF_FAILED``)
    يظفر بتلميحه الخاص (تحديث لإصدار رمز أمان جديد) — والباقي تلميح الرمز.
    """
    if code == "CSRF_FAILED":
        return _("انتهت صلاحية جلسة طلبك. حدّث الصفحة لإصدار رمز أمان جديد ثم أعد المحاولة.")
    return standard_hint(status)


def error_domain(status: int) -> str:
    """التصنيف الدلالي للرمز (validation/auth/permission/…) — يوجه الواجهة.

    يُقرأ من الحقل ``domain`` في جسم الـ JSON، ليستطيع الواجهة الطرفية
    (toast/صفحة) أن تتصرف: على auth تعرض زر تسجيل الدخول، على conflict زر
    تحديث، على rate_limit مؤقت انتظار — بلا إعادة كود في كل مسار وحده.
    """
    return ERROR_DOMAINS.get(status, "server")


def safe_details(details: Any) -> dict[str, Any]:
    """تنقية كائن ``details`` قبل إرساله للعميل — الحفرة الأخيرة للـ payload.

    القاعدة نفسها آنفة في ``safe_message`` لكنها على مستوى المفتاح والقيمة:
    لا مفاتيح تصادقية (كلمة مرور/رمز/بطاقة)، ولا قيم نصية تحمل أثراً
    تقنياً أو بيانات كبيرة، ولا أبنية (floats/lists/objects) — فالالتفاف
    على التنقية عبر ``details`` يجب أن يكون مستحيلاً أيضاً.
    """
    if not isinstance(details, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        if not isinstance(key, str) or _SENSITIVE_KEY_RE.search(key):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            cleaned[key] = value
        elif isinstance(value, str):
            text = value.strip()
            if 0 < len(text) <= 150 and not looks_technical(text):
                cleaned[key] = text
        if len(cleaned) >= 10:
            break
    return cleaned


def correlation_id() -> str:
    """معرّف ارتباط الطلب الحالي — يُنشأ إن لم يكن موجوداً.

    يقرأ من ``flask.g`` (يضبطه middleware التسجيل في كل طلب) ويقع على
    ContextVar عند غيابه، فلا يخرج ردّ خطأ بلا معرّف تتبّع. وقراءة ``g``
    خارج سياق التطبيق ترمي RuntimeError — وهي حالة موجودة فعلاً (بنّاء
    ردّ خطأ من مهمة/سكربت)، فلا يجوز أن تسقط الوحدة بسببها.
    """
    try:
        cid = getattr(g, "correlation_id", None)
    except RuntimeError:
        cid = None
    return cid or get_correlation_id()


def looks_technical(text: str) -> bool:
    """هل يحمل النص أثراً تقنياً (SQL/محرّك/مسار ملف/كائن بايثون)؟"""
    return bool(_TECHNICAL_LEAK_RE.search(text))


def safe_message(status: int, candidate: str | None = None) -> str:
    """رسالة آمنة للمستخدم: نص العمل إن كان نظيفاً، وإلا الرسالة المعيارية.

    نص العمل («رصيد المحفظة لا يكفي») يمرّ كما هو لأنه موجَّه للمستخدم فعلاً،
    وأي نص يحمل أثراً تقنياً أو يتجاوز حداً معقولاً يُستبدل بالرسالة المعيارية
    للحالة — القاعدة: لا تفصيل داخلي يصل إلى العميل.
    """
    fallback = standard_message(status)
    if candidate:
        text = str(candidate).strip()
        if text and len(text) <= 300 and not looks_technical(text):
            return text
    return fallback


def flash_error(candidate: str | None, category: str = "danger", status: int = 400) -> None:
    """يعرض رسالة خطأ في الواجهة (flash) بعد تنقيتها — نقطة واحدة لكل flash خطأ.

    مسارات الواجهات كانت تعرض نص الاستثناء كما هو (``flash(str(exc))``)، وهو
    منفذ تسريب يوازي استجابات الـ API: أي نص يحمل أثراً تقنياً (SQL/محرّك/مسار)
    يُستبدل بالرسالة المعيارية للحالة، ونص العمل يمرّ كما هو. الفئة (danger/
    warning/info) تبقى بيد المستدعي فلا يتغيّر شكل التنبيه.
    """
    flash(safe_message(status, candidate), category)


def error_payload(
    status: int,
    message: str | None = None,
    code: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """جسم خطأ JSON موحّد — بلا تفاصيل داخلية، ومع معرّف متابعة.

    المصدر الوحيد لشكل خطأ الـ API: ``app/core/api.api_error`` يبني عليه
    والمعالج العام هنا يبني عليه، فلا يمكن أن يختلف الشكل بين مسار ومسار.
    """
    return {
        "error": {
            "code": code or STATUS_CODES.get(status, f"ERR_{status}"),
            "domain": error_domain(status),
            "message": safe_message(status, message),
            "details": safe_details(details),
        },
        "meta": {
            "version": API_VERSION,
            "request_id": correlation_id(),
        },
    }


def wants_json() -> bool:
    """هل يتوقع العميل JSON؟ (مسارات API/health أو عميل لا يقبل HTML).

    غياب ترويسة ``Accept`` ليس تفضيلاً للـ JSON: طلب بلا ترويسة (متصفح قديم،
    أداة داخلية، عميل اختبار) يقبل أي صيغة، ومسارات الواجهة وجهتها الأصلية
    صفحة عربية — لذلك الافتراضي هنا HTML، وJSON يُختار فقط عن نية صريحة:
    مسار API/health، جسم JSON، أو عميل لا يقبل HTML (``accept_html`` خطأ وعنده
    صيغ أخرى مقبولة).
    """
    if request.path.startswith(("/api/", "/health")):
        return True
    if request.is_json:
        return True
    if not request.accept_mimetypes:
        return False  # لا ترويسة Accept → صفحة الواجهة العربية
    return not request.accept_mimetypes.accept_html


def template_for(status: int) -> str:
    """قالب الحالة: صفحتها المصمّمة إن وُجدت، وإلا القالب العام العربي.

    Werkzeug يعرض صفحته الإنجليزية لأي رمز بلا قالب (400/405/415 مثلاً)،
    والقالب العام يحمل الرسالة العربية الصحيحة للرمز نفسه — فلا نص إنجليزي
    مكشوف ولا رسالة مضلّلة عن رمز آخر.
    """
    return _HTML_TEMPLATES.get(status, _GENERIC_TEMPLATE)


def _is_unique_violation(exc: BaseException) -> bool:
    """انتهاك قيد فريد؟ (متوافق مع psycopg2 ``pgcode`` وpsycopg3 ``sqlstate``)"""
    orig = getattr(exc, "orig", None)
    return bool(
        orig is not None
        and (getattr(orig, "pgcode", None) == _UNIQUE_VIOLATION or getattr(orig, "sqlstate", None) == _UNIQUE_VIOLATION)
    )


def map_exception(exc: BaseException) -> tuple[int, str, str]:
    """يحوّل استثناءً غير متوقع إلى (رمز الحالة، رسالة عربية، رمز خطأ).

    التصنيف مقصود أن يكون ضيقاً: يُترجم فقط ما نفهم دلالته بدقة، وما عدا ذلك
    يبقى 500 عاماً — فلا يتحوّل خلل برمجي إلى «خطأ في مدخلاتك»، ولا عطل حقيقي
    يُبتلع بتصنيف لطيف.
    """
    from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

    from app.core.db import TxError

    if isinstance(exc, TxError):
        # خطأ منطق عمل وصل بلا التقاط: رسالته موجَّهة للمستخدم أصلاً.
        return 409, safe_message(409, str(exc)), "CONFLICT"
    if isinstance(exc, IntegrityError):
        # قيد فريد = تعارض يفهمه المستخدم وله إجراء (قد يكون السجل موجوداً).
        # أي قيد آخر (NOT NULL/مفتاح أجنبي) عطل برمجي: 500 برسالة عامة،
        # والتفصيل يبقى في السجل.
        if _is_unique_violation(exc):
            return 409, safe_message(409), "CONFLICT"
        return 500, standard_message(500), "INTERNAL_ERROR"
    if isinstance(exc, (OperationalError, DBAPIError)):
        return 503, safe_message(503), "SERVICE_UNAVAILABLE"
    # CSRF: أشهر خطأ يواجه المستخدم فعلاً، وله إجراء واضح (تحديث الصفحة).
    try:
        from flask_wtf.csrf import CSRFError
    except ImportError:  # pragma: no cover — flask_wtf غير مثبّت
        CSRFError = None
    if CSRFError is not None and isinstance(exc, CSRFError):
        return 400, _("انتهت صلاحية الجلسة. حدّث الصفحة ثم حاول مجدداً."), "CSRF_FAILED"
    return 500, standard_message(500), "INTERNAL_ERROR"


def log_error(exc: BaseException, status: int, *, code: str) -> str:
    """تسجيل الخطأ على الخادم فقط، وإرجاع معرّف المتابعة المعروض للمستخدم.

    التفاصيل (نوع الاستثناء، نصّه، تتبّعه للمستوى 5xx) تبقى في السجل، ويُخرج
    للمستخدم المعرّف وحده — نقطة الوصل الوحيدة بين ما يراه العميل وما يراه
    الفريق هي هذا المعرّف. لا تُسجَّل أجسام الطلبات ولا أي بيانات عميل.
    """
    ref = correlation_id()
    try:
        from flask_login import current_user

        user_id: int | str | None = current_user.id if current_user.is_authenticated else None
    except Exception:  # noqa: BLE001 — التسجيل لا يجوز أن يفشل بسبب سياق غائب
        user_id = None

    payload = {
        "request_id": ref,
        "method": getattr(request, "method", None),
        "path": getattr(request, "path", None),
        "status": status,
        "error_code": code,
        "error_domain": error_domain(status),
        "error_type": type(exc).__name__,
        "user_id": user_id,
    }
    if status >= 500:
        logger.error("unhandled_exception", exc_info=exc, error_detail=str(exc)[:500], **payload)
    elif status == 404:
        logger.debug("not_found", **payload)
    else:
        logger.info("request_error", error_detail=str(exc)[:300], **payload)
    return ref


def _json_error(status: int, code: str, message: str | None = None):
    return jsonify(error_payload(status, message=message, code=code)), status


def _wants_redirect_to_login() -> bool:
    """السلوك القائم للـ 401 قبل التوحيد: عميلَان فقط يحصلان على JSON — مسار
    API/health (كما في معالج /health القديم)، أو عميل لا يقبل HTML أصلاً —
    وكل من تبقّى (متصفح، أو طلب بلا ترويسة Accept كالأدوات وعميل الاختبار)
    كان يُوجَّه لصفحة الدخول. ``wants_json()`` أعمّ من هذا: غياب Accept عندها
    تفضيل HTML لغرض صفحات الخطأ العامة، لذا قرار التحويل هنا يقرأ الترويسة
    مباشرة حفاظاً على العقد القديم حرفياً."""
    if request.path.startswith(("/api/", "/health")):
        return False
    return request.accept_mimetypes.accept_html


def handle_http_exception(exc: HTTPException):
    """معالج كل استثناءات HTTP المقصودة (403/404/405/415/429...).

    ما ترفعه المسارات عبر ``abort`` يصل هنا: صفحة عربية للمتصفح، وJSON
    لمسارات الـ API، بوصف Werkzeug الإنجليزي مُستبعد من الحالتين.
    """
    status = exc.code or 500
    if status == 500:
        return handle_unexpected_exception(exc)

    # رمز HTTP عام قد يحمل دلالة أدقّ (CSRFError رمزه 400 لكن سببه جلسة
    # منتهية): الرسالة الأدقّ تُستخدم متى كان التصنيف معروفاً، وإلا رسالة الرمز.
    _mapped_status, mapped_message, mapped_code = map_exception(exc)
    code = STATUS_CODES.get(status, f"ERR_{status}")
    message = None
    if mapped_code == "CSRF_FAILED":
        code, message = mapped_code, mapped_message

    ref = log_error(exc, status, code=code)
    hint = hint_for(code, status)

    if status == 401:
        if _wants_redirect_to_login():
            return redirect(url_for("auth.login"))
        # العقد القديم لـ /health: المفتاح ``error`` نصّي — نحافظ عليه ونضيف
        # الرسالة العربية ومعرّف المتابعة بدل تغيير شكل يستهلكه العميل.
        from app.core.api import api_error

        response, _status = api_error(standard_message(401), 401, "UNAUTHORIZED")
        body = response.get_json()
        body["error"] = "unauthorized"
        body["message"] = standard_message(401)
        body["request_id"] = ref
        return jsonify(body), 401

    if wants_json():
        return _json_error(status, code, message=message)

    return (
        render_template(
            template_for(status),
            code=status,
            message=message or standard_message(status),
            hint=hint,
            request_id=ref,
        ),
        status,
    )


def handle_unexpected_exception(exc: BaseException):
    """معالج الاستثناءات غير المتوقعة — يسجّل الكل ويُظهر رسالة آمنة.

    ``exc`` قد يكون ``InternalServerError`` ملفوفاً حول الخطأ الأصلي (هكذا
    يمرّره Flask إلى معالج 500)؛ نصنّف الأصل لا اللفّافة، فلا تتحوّل UniqueViolation
    إلى 500 عام ولا العكس. ولا يخرج نص أي منهما إلى العميل مطلقاً: رسالة عربية
    معيارية + معرّف متابعة فقط.
    """
    original = getattr(exc, "original_exception", None) or exc
    status, message, code = map_exception(original)
    ref = log_error(original, status, code=code)

    # أي كتابة مفتوحة تُلغى: استثناء في منتصف معاملة لا يجوز أن يترك أثراً.
    try:
        from app.extensions import db

        db.session.rollback()
    except Exception:  # noqa: BLE001 — لا سياق تطبيق/جلسة
        logger.debug("rollback_skipped", request_id=ref)

    if wants_json():
        return _json_error(status, code, message=message)
    return (
        render_template(
            template_for(status),
            code=status,
            message=message,
            hint=standard_hint(status),
            request_id=ref,
        ),
        status,
    )


def register_error_handlers(app: Flask) -> None:
    """يسجّل معالجات الأخطاء العامة على التطبيق (من المصنع مرة واحدة).

    تُسجَّل لكل رمز على حدة (لا صنف واحد): ``handle_unexpected_exception``
    يحتاج أن يستقبل 500 وحدَه ليعرف أن الخطأ غير متوقع، والرموز الأخرى تُعرض
    برسائلها. ويُسجَّل ``HTTPException`` كذلك للرموز غير المذكورة (406/419…)
    فلا تسقط على صفحة Werkzeug الإنجليزية، ويبقى ``Exception`` شبكة أمان.
    """
    for status in sorted(STATUS_CODES):
        app.register_error_handler(status, _make_http_handler(status))
    app.register_error_handler(HTTPException, handle_http_exception)
    app.register_error_handler(Exception, handle_unexpected_exception)


def _make_http_handler(status: int):
    """يبني دالة معالجة لرمز واحد — تُمرَّر للـ Flask كمعالج مستقل.

    التسجيل لكل رمز (لا استثناء عام واحد) هو ما يجعل ترتيب Flask يختار
    ``handle_unexpected_exception`` للـ 500، فيُسجَّل التتبّع الكامل ويُلغى
    ما لم يُكتب، بينما 403/404 تحصل على قوالبها.
    """

    def _handler(exc: BaseException):
        if status == 500:
            return handle_unexpected_exception(exc)
        if isinstance(exc, HTTPException):
            return handle_http_exception(exc)
        # رُمي استثناء غير HTTP وصُنّف لهذا الرمز (مثلاً CSRF يمثّل 400):
        # يُوضع في قالب الرمز مع رسالة الخطأ الأصلية بعد تنقيتها.
        original_status, message, code = map_exception(exc)
        if original_status != status:
            return handle_unexpected_exception(exc)
        ref = log_error(exc, status, code=code)
        if wants_json():
            return _json_error(status, code, message=message)
        return (
            render_template(
                template_for(status),
                code=status,
                message=message,
                hint=hint_for(code, status),
                request_id=ref,
            ),
            status,
        )

    _handler.__name__ = f"handle_error_{status}"
    return _handler


__all__ = [
    "API_VERSION",
    "ERROR_DOMAINS",
    "STATUS_CODES",
    "correlation_id",
    "error_domain",
    "error_payload",
    "flash_error",
    "handle_http_exception",
    "handle_unexpected_exception",
    "hint_for",
    "log_error",
    "looks_technical",
    "map_exception",
    "register_error_handlers",
    "safe_details",
    "safe_message",
    "standard_hint",
    "standard_message",
    "template_for",
    "wants_json",
]
