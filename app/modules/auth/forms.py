"""نماذج المصادقة (Flask-WTF)"""
from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField, RadioField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class RegisterForm(FlaskForm):
    name_ar = StringField("الاسم (عربي)", validators=[DataRequired(), Length(min=2, max=120)])
    email = EmailField("البريد الإلكتروني", validators=[DataRequired(), Email()])
    role = RadioField(
        "أنا",
        choices=[("student", "طالب"), ("teacher", "معلم"), ("parent", "ولي أمر")],
        default="student",
        validators=[DataRequired()],
    )
    password = PasswordField("كلمة المرور", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField("تأكيد كلمة المرور", validators=[DataRequired(), EqualTo("password", message="كلمتا المرور غير متطابقتين")])
    submit = SubmitField("إنشاء الحساب")


class LoginForm(FlaskForm):
    email = EmailField("البريد الإلكتروني", validators=[DataRequired(), Email()])
    password = PasswordField("كلمة المرور", validators=[DataRequired()])
    submit = SubmitField("تسجيل الدخول")


class ForgotPasswordForm(FlaskForm):
    email = EmailField("البريد الإلكتروني", validators=[DataRequired(), Email()])
    submit = SubmitField("إرسال رابط إعادة التعيين")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("كلمة المرور الجديدة", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField("تأكيد كلمة المرور", validators=[DataRequired(), EqualTo("password", message="كلمتا المرور غير متطابقتين")])
    submit = SubmitField("حفظ كلمة المرور الجديدة")
