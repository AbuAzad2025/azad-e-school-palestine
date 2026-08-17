"""إرسال البريد الإلكتروني — مُغلّف بعلم تفعيل EMAIL_ENABLED.

يُستخدم Flask-Mail لإرسال رسائل HTML. يسجل فقط في وضع التطوير أو عند تعطيل البريد.
"""

import logging

from flask import current_app
from flask_mail import Message

from app.extensions import mail

logger = logging.getLogger(__name__)


def _send(to: str, subject: str, html_body: str) -> bool:
    """إرسال رسالة بريد. يعيد True عند النجاح، False عند الفشل أو التعطيل."""
    if not current_app.config.get("EMAIL_ENABLED", False):
        logger.info("[EMAIL-DISABLED] to=%s subject=%s", to, subject)
        return False

    try:
        msg = Message(subject=subject, recipients=[to], html=html_body)
        mail.send(msg)
        logger.info("[EMAIL-SENT] to=%s subject=%s", to, subject)
        return True
    except Exception:
        logger.exception("[EMAIL-FAILED] to=%s subject=%s", to, subject)
        return False


def send_welcome_email(user) -> bool:
    """رسالة ترحيب بعد قبول التسجيل."""
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">مرحباً {user.name_ar or user.email}!</h2>
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
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">تم اعتماد دفعك</h2>
        <p>مرحباً {user.name_ar or user.email}،</p>
        <p>تم اعتماد دفعك بمبلغ <strong>{payment.amount} {sub.currency}</strong> (مرجع: {payment.reference}).</p>
        <p>اشتراكك الآن نشط حتى <strong>{sub.end_at.strftime("%Y-%m-%d") if sub.end_at else "—"}</strong>.</p>
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
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #c53030;">رُفض دفعك</h2>
        <p>مرحباً {user.name_ar or user.email}،</p>
        <p>لم يُعتمد دفعك بمبلغ <strong>{payment.amount} {sub.currency}</strong> (مرجع: {payment.reference}).</p>
        <p>يرجى مراجعة البيانات وإعادة الإرسال.</p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(user.email, "رُفض دفعك — منصة مدرسة أزاد الإلكترونية", html)


def send_grade_published_email(student, assignment, mark) -> bool:
    """رسالة إشعار بدرجتك في واجب/اختبار."""
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">تم نشر درجتك</h2>
        <p>مرحباً {student.name_ar or student.email}،</p>
        <p>تم تسجيل درجتك في <strong>{assignment.title}</strong>.</p>
        <p>درجتك: <strong>{mark} / {assignment.max_mark or "—"}</strong></p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(student.email, "تم نشر درجتك — منصة مدرسة أزاد الإلكترونية", html)


def send_quiz_result_email(student, quiz, score) -> bool:
    """رسالة إشعار بنتيجة الاختبار."""
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #014e7c;">نتيجة الاختبار</h2>
        <p>مرحباً {student.name_ar or student.email}،</p>
        <p>أكملت اختبار <strong>{quiz.title}</strong>.</p>
        <p>درجتك: <strong>{score}%</strong></p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(student.email, "نتيجة اختبارك — منصة مدرسة أزاد الإلكترونية", html)


def send_absence_alert_email(parent_user, student, days) -> bool:
    """رسالة إشعار لولي الأمر بغياب الطالب."""
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #c53030;">تنبيه: غياب الطالب</h2>
        <p>مرحباً {parent_user.name_ar or parent_user.email}،</p>
        <p>
            لم يسجل الطالب <strong>{student.name_ar or student.email}</strong>
            نشاطاً على المنصة منذ <strong>{days} يوم</strong>.
        </p>
        <p>يُرجى متابعة الطالب.</p>
        <p style="margin-top: 2rem; color: #666; font-size: 0.9em;">
            هذه رسالة تلقائية، يُرجى عدم الرد عليها.
        </p>
    </div>
    """
    return _send(parent_user.email, "تنبيه: غياب الطالب — منصة مدرسة أزاد الإلكترونية", html)
