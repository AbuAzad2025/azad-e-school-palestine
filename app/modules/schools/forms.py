"""نماذج المدارس والصفوف"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import DecimalField, HiddenField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class SchoolForm(FlaskForm):
    name_ar = StringField(_("اسم المدرسة (عربي)"), validators=[DataRequired(), Length(min=2, max=200)])
    name_en = StringField(_("اسم المدرسة (إنجليزي)"), validators=[Optional(), Length(max=200)])
    domain = StringField(_("النطاق"), validators=[Optional(), Length(max=200)])
    submit = SubmitField(_("إنشاء المدرسة"))


class ClassForm(FlaskForm):
    subject = StringField(_("المادة"), validators=[DataRequired(), Length(max=120)])
    grade_id = SelectField(_("الصف الدراسي"), coerce=int, validators=[DataRequired()])
    semester = SelectField(
        _("الفصل"),
        choices=[("first", _("الأول")), ("second", _("الثاني")), ("annual", _("السنوي"))],
        default="first",
    )
    name = StringField(_("اسم الصف (اختياري)"), validators=[Optional(), Length(max=200)])
    price_first_term = DecimalField(_("سعر الفصل الأول"), validators=[Optional()], places=2)
    price_second_term = DecimalField(_("سعر الفصل الثاني"), validators=[Optional()], places=2)
    price_annual = DecimalField(_("سعر السنوي"), validators=[Optional()], places=2)
    submit = SubmitField(_("إنشاء الصف"))


class JoinClassForm(FlaskForm):
    code = StringField(_("رمز الانضمام"), validators=[DataRequired(), Length(min=4, max=16)])
    submit = SubmitField(_("انضمام"))


class GradeForm(FlaskForm):
    grade_level = IntegerField(_("المستوى (1..12)"), validators=[DataRequired(), NumberRange(min=1, max=12)])
    name_ar = StringField(_("الاسم (عربي)"), validators=[Optional(), Length(max=200)])
    submit = SubmitField(_("إضافة مستوى"))


class AssignTeacherForm(FlaskForm):
    teacher_id = HiddenField("teacher_id", validators=[DataRequired()])
    submit = SubmitField(_("تعيين المعلم"))
