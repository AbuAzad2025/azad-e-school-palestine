"""نماذج المحتوى"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import BooleanField, FileField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class UnitForm(FlaskForm):
    title = StringField(_("عنوان الوحدة"), validators=[DataRequired(), Length(max=300)])
    submit = SubmitField(_("إضافة وحدة"))


class LessonForm(FlaskForm):
    title = StringField(_("عنوان الدرس"), validators=[DataRequired(), Length(max=300)])
    unit_id = SelectField(_("الوحدة"), coerce=int, validators=[Optional()])
    body_html = TextAreaField(_("محتوى الدرس (HTML)"), validators=[Optional()])
    is_offline_available = BooleanField(_("متاح للوضع غير المتصل"), default=False)
    submit = SubmitField(_("حفظ الدرس"))


class AttachmentForm(FlaskForm):
    file = FileField(_("ملف المرفق"), validators=[DataRequired()])
    title = StringField(_("عنوان المرفق"), validators=[Optional(), Length(max=300)])
    submit = SubmitField(_("رفع"))


class YoutubeForm(FlaskForm):
    url = StringField(_("رابط فيديو YouTube"), validators=[DataRequired(), Length(max=500)])
    title = StringField(_("عنوان الفيديو"), validators=[Optional(), Length(max=300)])
    submit = SubmitField(_("إضافة الفيديو"))
