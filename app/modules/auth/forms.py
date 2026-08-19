"""نماذج المصادقة (Flask-WTF)"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField, RadioField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError


def password_policy_validator(form, field):
    """مُدقق مخصص لسياسة كلمة المرور."""
    from app.core.security import validate_password_policy

    ok, msg = validate_password_policy(field.data)
    if not ok:
        raise ValidationError(_(msg))


class RegisterForm(FlaskForm):
    name_ar = StringField(_("الاسم (عربي)"), validators=[DataRequired(), Length(min=2, max=120)])
    email = EmailField(_("البريد الإلكتروني"), validators=[DataRequired(), Email()])
    role = RadioField(
        _("أنا"),
        choices=[("student", _("طالب")), ("teacher", _("معلم")), ("parent", _("ولي أمر"))],
        default="student",
        validators=[DataRequired()],
    )
    school_join_code = StringField(_("كود الانضمام للمدرسة (اختياري)"), validators=[Length(max=20)])
    password = PasswordField(_("كلمة المرور"), validators=[DataRequired(), password_policy_validator])
    confirm = PasswordField(
        _("تأكيد كلمة المرور"),
        validators=[DataRequired(), EqualTo("password", message=_("كلمتا المرور غير متطابقتين"))],
    )
    submit = SubmitField(_("إنشاء الحساب"))


class LoginForm(FlaskForm):
    email = EmailField(_("البريد الإلكتروني"), validators=[DataRequired(), Email()])
    password = PasswordField(_("كلمة المرور"), validators=[DataRequired()])
    submit = SubmitField(_("تسجيل الدخول"))


class ForgotPasswordForm(FlaskForm):
    email = EmailField(_("البريد الإلكتروني"), validators=[DataRequired(), Email()])
    submit = SubmitField(_("إرسال رابط إعادة التعيين"))


class ResetPasswordForm(FlaskForm):
    password = PasswordField(_("كلمة المرور الجديدة"), validators=[DataRequired(), password_policy_validator])
    confirm = PasswordField(
        _("تأكيد كلمة المرور"),
        validators=[DataRequired(), EqualTo("password", message=_("كلمتا المرور غير متطابقتين"))],
    )
    submit = SubmitField(_("حفظ كلمة المرور الجديدة"))
