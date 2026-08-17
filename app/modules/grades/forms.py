"""نماذج الواجبات والدرجات"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import DecimalField, FileField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class AssignmentForm(FlaskForm):
    title = StringField(_("عنوان الواجب"), validators=[DataRequired(), Length(max=300)])
    body = TextAreaField(_("شرح الواجب"), validators=[Optional()])
    max_mark = DecimalField(_("الدرجة القصوى"), validators=[Optional()], places=2)
    submit = SubmitField(_("نشر الواجب"))


class SubmissionForm(FlaskForm):
    body = TextAreaField(_("إجابتك"), validators=[Optional()])
    file = FileField(_("ملف"), validators=[Optional()])
    submit = SubmitField(_("تسليم"))


class GradeSubmissionForm(FlaskForm):
    mark = DecimalField(_("الدرجة"), validators=[DataRequired(), NumberRange(min=0)], places=2)
    feedback = TextAreaField(_("ملاحظات"), validators=[Optional()])
    submit = SubmitField(_("تصحيح"))


class CategoryForm(FlaskForm):
    name = StringField(_("اسم القسم"), validators=[DataRequired(), Length(max=200)])
    weight = DecimalField(_("الوزن"), validators=[Optional()], places=2)
    submit = SubmitField(_("إضافة قسم"))


class GradeItemForm(FlaskForm):
    title = StringField(_("عنوان البند"), validators=[DataRequired(), Length(max=300)])
    max_mark = DecimalField(_("الدرجة القصوى"), validators=[Optional()], places=2)
    kind = SelectField(
        _("النوع"),
        choices=[("exam", _("اختبار")), ("assignment", _("واجب")), ("project", _("مشروع")), ("attendance", _("حضور"))],
        default="exam",
    )
    submit = SubmitField(_("إضافة بند"))
