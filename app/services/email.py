"""إرسال البريد الإلكتروني — مُغلّف بعلم تفعيل EMAIL_ENABLED.

يُستخدم Flask-Mail لإرسال رسائل HTML. يسجل فقط في وضع التطوير أو عند تعطيل البريد.
"""

from flask import current_app
from flask_mail import Message
from markupsafe import escape

from app.core.logging import get_logger
from app.extensions import mail

logger = get_logger(__name__)


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


def send_welcome_email(user) -> bool:
    """رسالة ترحيب بعد قبول التسجيل."""
    name = escape(user.name_ar or user.email)
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">مرحباً {name}!</h2>
        <p>تم قبول حسابك في منصة مدرسة أزاد الإلكترونية.</p>
        <p>يمكنك الآن تسجيل الدخول والبدء في استخدام المنصة.</p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(user.email, "مرحباً بك في منصة مدرسة أزاد الإلكترونية", html)


def send_payment_approved_email(payment) -> bool:
    """رسالة تأكيد اعتماد الدفع وتفعيل الاشتراك."""
    sub = payment.subscription
    user = sub.user
    name = escape(user.name_ar or user.email)
    amount = escape(str(payment.amount))
    currency = escape(sub.currency)
    reference = escape(payment.reference)
    end_date = escape(sub.end_at.strftime("%Y-%m-%d") if sub.end_at else "—")
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">تم اعتماد دفعك</h2>
        <p>مرحباً {name}،</p>
        <p>تم اعتماد دفعك بمبلغ <strong>{amount} {currency}</strong> (مرجع: {reference}).</p>
        <p>اشتراكك الآن نشط حتى <strong>{end_date}</strong>.</p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(user.email, "تم اعتماد دفعك — منصة مدرسة أزاد الإلكترونية", html)


def send_payment_rejected_email(payment) -> bool:
    """رسالة إشعار برفض الدفع."""
    sub = payment.subscription
    user = sub.user
    name = escape(user.name_ar or user.email)
    amount = escape(str(payment.amount))
    currency = escape(sub.currency)
    reference = escape(payment.reference)
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #c53030;">رُفض دفعك</h2>
        <p>مرحباً {name}،</p>
        <p>لم يُعتمد دفعك بمبلغ <strong>{amount} {currency}</strong> (مرجع: {reference}).</p>
        <p>يرجى مراجعة البيانات وإعادة الإرسال.</p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(user.email, "رُفض دفعك — منصة مدرسة أزاد الإلكترونية", html)


def send_grade_published_email(student, assignment, mark) -> bool:
    """رسالة إشعار بدرجتك في واجب/اختبار."""
    name = escape(student.name_ar or student.email)
    title = escape(assignment.title)
    max_mark = escape(str(assignment.max_mark or "—"))
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">تم نشر درجتك</h2>
        <p>مرحباً {name}،</p>
        <p>تم تسجيل درجتك في <strong>{title}</strong>.</p>
        <p>درجتك: <strong>{escape(str(mark))} / {max_mark}</strong></p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(student.email, "تم نشر درجتك — منصة مدرسة أزاد الإلكترونية", html)


def send_quiz_result_email(student, quiz, score) -> bool:
    """رسالة إشعار بنتيجة الاختبار."""
    name = escape(student.name_ar or student.email)
    title = escape(quiz.title)
    score_esc = escape(str(score))
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">نتيجة الاختبار</h2>
        <p>مرحباً {name}،</p>
        <p>أكملت اختبار <strong>{title}</strong>.</p>
        <p>درجتك: <strong>{score_esc}%</strong></p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(student.email, "نتيجة اختبارك — منصة مدرسة أزاد الإلكترونية", html)


def send_absence_alert_email(parent_user, student, days) -> bool:
    """رسالة إشعار لولي الأمر بغياب الطالب."""
    parent_name = escape(parent_user.name_ar or parent_user.email)
    student_name = escape(student.name_ar or student.email)
    days_str = escape(str(days))
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #c53030;">تنبيه: غياب الطالب</h2>
        <p>مرحباً {parent_name}،</p>
        <p>
            لم يسجل الطالب <strong>{student_name}</strong>
            نشاطاً على المنصة منذ <strong>{days_str} يوم</strong>.
        </p>
        <p>يُرجى متابعة الطالب.</p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(parent_user.email, "تنبيه: غياب الطالب — منصة مدرسة أزاد الإلكترونية", html)


def send_payment_reminder_email(subscription, days_until_expiry: int) -> bool:
    """رسالة تذكير بتجديد الاشتراك."""
    # تحميل العلاقات المطلوبة لتجنب DetachedInstanceError
    from app.extensions import db

    sub = db.session.get(subscription.__class__, subscription.id)
    if not sub:
        return False
    user = sub.user
    plan = sub.plan
    name = escape(user.name_ar or user.email)
    plan_name = escape(plan.name)
    days_str = escape(str(days_until_expiry))
    end_date = escape(sub.end_at.strftime("%Y-%m-%d") if sub.end_at else "—")
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">تذكير: تجديد الاشتراك</h2>
        <p>مرحباً {name}،</p>
        <p>اشتراكك في <strong>{plan_name}</strong> سينتهي خلال
           <strong>{days_str} يوم</strong>.</p>
        <p>
            لتجنب انقطاع الخدمة، يرجى تجديد الاشتراك قبل تاريخ الانتهاء:
            <strong>{end_date}</strong>.
        </p>
        <p style="margin-top: 1.5rem;">
            <a href="{{ url_for('billing.class_billing', class_id={sub.class_id}, _external=True) }}"
               style="background: #014e7c; color: white; padding: 0.75rem 1.5rem;
                      text-decoration: none; border-radius: 4px; display: inline-block;">
                تجديد الاشتراك الآن
            </a>
        </p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(user.email, f"تذكير: تجديد اشتراكك خلال {days_until_expiry} يوم — منصة مدرسة أزاد الإلكترونية", html)


def send_contact_reply_email(contact_msg, reply_text: str) -> bool:
    """إرسال رد على رسالة تواصل للمستخدم."""
    name = escape(contact_msg.name)
    subject = escape(contact_msg.subject)
    reply = escape(reply_text)
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">رد على رسالتك</h2>
        <p>مرحباً {name}،</p>
        <p>شكراً لتواصلكم معنا. بخصوص رسالتكم: <strong>{subject}</strong></p>
        <div style="background: #f5f5f5; padding: 1rem; border-radius: 4px; margin: 1rem 0;">
            <p style="margin: 0; white-space: pre-wrap;">{reply}</p>
        </div>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(contact_msg.email, f"رد: {contact_msg.subject} — منصة مدرسة أزاد الإلكترونية", html)
