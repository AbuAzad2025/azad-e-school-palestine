"""نماذج التقييم"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class QuizForm(FlaskForm):
    title = StringField(_("عنوان الاختبار"), validators=[DataRequired(), Length(max=300)])
    duration_min = IntegerField(_("المدة (دقائق)"), validators=[Optional(), NumberRange(min=1)])
    attempts_allowed = IntegerField(
        _("عدد المحاولات"), validators=[DataRequired(), NumberRange(min=1, max=10)], default=1
    )
    shuffle = BooleanField(_("خلط الأسئلة"))
    show_answers_after = BooleanField(_("إظهار الإجابات بعد التسليم"))
    submit = SubmitField(_("حفظ الاختبار"))


class QuestionForm(FlaskForm):
    qtype = SelectField(
        _("النوع"),
        choices=[
            ("mcq", _("اختيار من متعدد")),
            ("true_false", _("صح/خطأ")),
            ("essay", _("مقالي")),
        ],
        default="mcq",
    )
    prompt = StringField(_("السؤال"), validators=[DataRequired(), Length(max=1000)])
    mark = IntegerField(_("الدرجة"), validators=[DataRequired(), NumberRange(min=1, max=100)], default=1)
    option_a = StringField(_("الخيار أ"), validators=[Optional()])
    option_b = StringField(_("الخيار ب"), validators=[Optional()])
    option_c = StringField(_("الخيار ج"), validators=[Optional()])
    option_d = StringField(_("الخيار د"), validators=[Optional()])
    correct_index = SelectField(
        _("الإجابة الصحيحة"),
        choices=[("0", "أ"), ("1", "ب"), ("2", "ج"), ("3", "د")],
        default="0",
    )
    correct_tf = SelectField(_("الإجابة"), choices=[("true", _("صح")), ("false", _("خطأ"))], default="true")
    submit = SubmitField(_("إضافة السؤال"))
