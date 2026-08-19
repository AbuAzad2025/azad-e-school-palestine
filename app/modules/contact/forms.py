"""نماذج صفحة التواصل"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


class ContactForm(FlaskForm):
    name = StringField(_("الاسم"), validators=[DataRequired(), Length(max=200)])
    email = StringField(_("البريد الإلكتروني"), validators=[DataRequired(), Email()])
    phone = StringField(_("الهاتف"), validators=[Optional(), Length(max=30)])
    subject = StringField(_("الموضوع"), validators=[DataRequired(), Length(max=200)])
    message = TextAreaField(_("الرسالة"), validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField(_("إرسال"))
