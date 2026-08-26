"""إرسال البريد الإلكتروني — مُغلّف بعلم تفعيل EMAIL_ENABLED.

يُستخدم Flask-Mail لإرسال رسائل HTML. يسجل فقط في وضع التطوير أو عند تعطيل البريد.
كل رسالة تُصيَّر بلغة **المستلم** (`user.locale`) لا لغة الجلسة الحالية،
عبر `force_locale` أثناء بناء النص.
"""

from datetime import datetime

from babel.dates import format_date as babel_format_date
from flask import current_app, url_for
from flask_babel import force_locale
from flask_mail import Message
from markupsafe import escape

from app.core.i18n import _
from app.core.logging import get_logger
from app.extensions import mail

logger = get_logger(__name__)

_DEFAULT_LOCALE = "ar"


def _recipient_locale(user) -> str:
    """لغة المستلم — حقل User.locale مع fallback آمن."""
    return getattr(user, "locale", None) or _DEFAULT_LOCALE


def _dir(locale: str) -> str:
    """اتجاه العرض حسب اللغة."""
    return "rtl" if locale.startswith("ar") else "ltr"


def _fmt_date(value: datetime | None, locale: str) -> str:
    """تاريخ بصيغة Babel متوافقة مع لغة المستلم."""
    if not value:
        return "—"
    try:
        return babel_format_date(value, format="medium", locale=locale)
    except (ValueError, TypeError):
        return value.strftime("%Y-%m-%d")


def _send(to: str, subject: str, html_body: str) -> bool:
    """إرسال رسالة بريد. يعيد True عند النجاح، False عند الفشل أو التعطيل."""
    log = logger.bind(service="email", to=to, subject=subject)
    if not current_app.config.get("EMAIL_ENABLED", False):
        log.info("email_disabled")
        return False

    try:
        msg = Message(subject=subject, recipients=[to], html=html_body)
        mail.send(msg)
        log.info("email_sent")
        return True
    except Exception:
        log.exception("email_failed")
        return False


def _footer() -> str:
    """تذييل موحد لكل الرسائل."""
    return (
        '<p style="margin-top: 2rem; color: #666; font-size: 0.9em;">'
        f"{_('هذه رسالة تلقائية، يُرجى عدم الرد عليها.')}"
        "</p>"
    )


def send_welcome_email(user) -> bool:
    """رسالة ترحيب بعد قبول التسجيل."""
    loc = _recipient_locale(user)
    name = escape(user.name_ar or user.email)
    with force_locale(loc):
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">{_("مرحباً %(name)s!", name=name)}</h2>
        <p>{_("تم قبول حسابك في منصة مدرسة أزاد الإلكترونية.")}</p>
        <p>{_("يمكنك الآن تسجيل الدخول والبدء في استخدام المنصة.")}</p>
        {_footer()}
    </div>
    """
        return _send(user.email, _("مرحباً بك في منصة مدرسة أزاد الإلكترونية"), html)


def send_payment_approved_email(payment) -> bool:
    """رسالة تأكيد اعتماد الدفع وتفعيل الاشتراك."""
    sub = payment.subscription
    user = sub.user
    loc = _recipient_locale(user)
    name = escape(user.name_ar or user.email)
    amount = escape(str(payment.amount))
    currency = escape(sub.currency)
    reference = escape(payment.reference)
    end_date = escape(_fmt_date(sub.end_at, loc))
    with force_locale(loc):
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">{_("تم اعتماد دفعك")}</h2>
        <p>{_("مرحباً %(name)s،", name=name)}</p>
        <p>{_("تم اعتماد دفعك بمبلغ")} <strong>{amount} {currency}</strong> ({_("مرجع")}: {reference}).</p>
        <p>{_("اشتراكك الآن نشط حتى")} <strong>{end_date}</strong>.</p>
        {_footer()}
    </div>
    """
        return _send(user.email, _("تم اعتماد دفعك — منصة مدرسة أزاد الإلكترونية"), html)


def send_payment_rejected_email(payment) -> bool:
    """رسالة إشعار برفض الدفع."""
    sub = payment.subscription
    user = sub.user
    loc = _recipient_locale(user)
    name = escape(user.name_ar or user.email)
    amount = escape(str(payment.amount))
    currency = escape(sub.currency)
    reference = escape(payment.reference)
    with force_locale(loc):
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #c53030;">{_("رُفض دفعك")}</h2>
        <p>{_("مرحباً %(name)s،", name=name)}</p>
        <p>{_("لم يُعتمد دفعك بمبلغ")} <strong>{amount} {currency}</strong> ({_("مرجع")}: {reference}).</p>
        <p>{_("يرجى مراجعة البيانات وإعادة الإرسال.")}</p>
        {_footer()}
    </div>
    """
        return _send(user.email, _("رُفض دفعك — منصة مدرسة أزاد الإلكترونية"), html)


def send_grade_published_email(student, assignment, mark) -> bool:
    """رسالة إشعار بدرجتك في واجب/اختبار."""
    loc = _recipient_locale(student)
    name = escape(student.name_ar or student.email)
    title = escape(assignment.title)
    max_mark = escape(str(assignment.max_mark or "—"))
    with force_locale(loc):
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">{_("تم نشر درجتك")}</h2>
        <p>{_("مرحباً %(name)s،", name=name)}</p>
        <p>{_("تم تسجيل درجتك في")} <strong>{title}</strong>.</p>
        <p>{_("درجتك")}: <strong>{escape(str(mark))} / {max_mark}</strong></p>
        {_footer()}
    </div>
    """
        return _send(student.email, _("تم نشر درجتك — منصة مدرسة أزاد الإلكترونية"), html)


def send_quiz_result_email(student, quiz, score) -> bool:
    """رسالة إشعار بنتيجة الاختبار."""
    loc = _recipient_locale(student)
    name = escape(student.name_ar or student.email)
    title = escape(quiz.title)
    score_esc = escape(str(score))
    with force_locale(loc):
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">{_("نتيجة الاختبار")}</h2>
        <p>{_("مرحباً %(name)s،", name=name)}</p>
        <p>{_("أكملت اختبار")} <strong>{title}</strong>.</p>
        <p>{_("درجتك")}: <strong>{score_esc}%</strong></p>
        {_footer()}
    </div>
    """
        return _send(student.email, _("نتيجة اختبارك — منصة مدرسة أزاد الإلكترونية"), html)


def send_absence_alert_email(parent_user, student, days) -> bool:
    """رسالة إشعار لولي الأمر بغياب الطالب."""
    loc = _recipient_locale(parent_user)
    parent_name = escape(parent_user.name_ar or parent_user.email)
    student_name = escape(student.name_ar or student.email)
    days_str = escape(str(days))
    with force_locale(loc):
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #c53030;">{_("تنبيه: غياب الطالب")}</h2>
        <p>{_("مرحباً %(name)s،", name=parent_name)}</p>
        <p>
            {_("لم يسجل الطالب")}
            <strong>{student_name}</strong>
            {_("نشاطاً على المنصة منذ")}
            <strong>{_("%(days)s يوم", days=days_str)}</strong>.
        </p>
        <p>{_("يُرجى متابعة الطالب.")}</p>
        {_footer()}
    </div>
    """
        return _send(parent_user.email, _("تنبيه: غياب الطالب — منصة مدرسة أزاد الإلكترونية"), html)


def send_payment_reminder_email(subscription, days_until_expiry: int) -> bool:
    """رسالة تذكير بتجديد الاشتراك."""
    # تحميل العلاقات المطلوبة لتجنب DetachedInstanceError
    from app.extensions import db

    sub = db.session.get(subscription.__class__, subscription.id)
    if not sub:
        return False
    user = sub.user
    plan = sub.plan
    loc = _recipient_locale(user)
    name = escape(user.name_ar or user.email)
    plan_name = escape(plan.name)
    days_str = escape(str(days_until_expiry))
    end_date = escape(_fmt_date(sub.end_at, loc))
    with force_locale(loc):
        renew_url = url_for("billing.class_billing", class_id=sub.class_id, _external=True)
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">{_("تذكير: تجديد الاشتراك")}</h2>
        <p>{_("مرحباً %(name)s،", name=name)}</p>
        <p>{_("اشتراكك في")} <strong>{plan_name}</strong> {_("سينتهي خلال")}
           <strong>{_("%(days)s يوم", days=days_str)}</strong>.</p>
        <p>
            {_("لتجنب انقطاع الخدمة، يرجى تجديد الاشتراك قبل تاريخ الانتهاء:")}
            <strong>{end_date}</strong>.
        </p>
        <p style="margin-top: 1.5rem;">
            <a href="{renew_url}"
               style="background: #014e7c; color: white; padding: 0.75rem 1.5rem;
                      text-decoration: none; border-radius: 4px; display: inline-block;">
                {_("تجديد الاشتراك الآن")}
            </a>
        </p>
        {_footer()}
    </div>
    """
        return _send(
            user.email,
            _("تذكير: تجديد اشتراكك خلال %(days)s يوم — منصة مدرسة أزاد الإلكترونية", days=days_until_expiry),
            html,
        )


def send_contact_reply_email(contact_msg, reply_text: str) -> bool:
    """إرسال رد على رسالة تواصل للمستخدم."""
    name = escape(contact_msg.name)
    subject = escape(contact_msg.subject)
    reply = escape(reply_text)
    # رسائل التواصل لا ترتبط بمستخدم له locale — نستخدم الافتراضية
    loc = _DEFAULT_LOCALE
    with force_locale(loc):
        html = f"""
    <div dir="{_dir(loc)}" lang="{loc}" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">{_("رد على رسالتك")}</h2>
        <p>{_("مرحباً %(name)s،", name=name)}</p>
        <p>{_("شكراً لتواصلكم معنا. بخصوص رسالتكم:")} <strong>{subject}</strong></p>
        <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px; margin: 1rem 0;">
            <p style="margin: 0; white-space: pre-wrap;">{reply}</p>
        </div>
        {_footer()}
    </div>
    """
        email_subject = _("رد: %(subject)s — منصة مدرسة أزاد الإلكترونية", subject=contact_msg.subject)
        return _send(contact_msg.email, email_subject, html)
