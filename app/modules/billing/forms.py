"""نماذج الاشتراكات"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import (
    DecimalField,
    FileField,
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class PlanForm(FlaskForm):
    name = StringField(_("اسم الخطة"), validators=[DataRequired(), Length(max=200)])
    plan = SelectField(
        _("النوع"),
        choices=[("first_term", _("الفصل الأول")), ("second_term", _("الفصل الثاني")), ("annual", _("السنوي"))],
        default="first_term",
    )
    price = DecimalField(_("السعر"), validators=[DataRequired(), NumberRange(min=0)], places=2)
    currency = StringField(_("العملة"), validators=[DataRequired(), Length(max=3)], default="ILS")
    duration_days = IntegerField(_("مدة الاشتراك (أيام)"), validators=[Optional(), NumberRange(min=1)], default=180)
    submit = SubmitField(_("حفظ الخطة"))


class SubscribeForm(FlaskForm):
    plan_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField(_("اشترك"))


class PaymentForm(FlaskForm):
    reference = StringField(_("رقم مرجع التحويل"), validators=[DataRequired(), Length(max=200)])
    amount = DecimalField(_("المبلغ"), validators=[DataRequired(), NumberRange(min=0)], places=2)
    note = TextAreaField(_("ملاحظات"), validators=[Optional()])
    receipt = FileField(_("صورة الإيصال (اختياري)"), validators=[Optional()])
    submit = SubmitField(_("إرسال الدفع للاعتماد"))
