"""نماذج روابط الأسرة"""

from decimal import Decimal

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LinkCodeForm(FlaskForm):
    code = StringField(_("رمز الربط"), validators=[DataRequired(), Length(min=6, max=12)])
    submit = SubmitField(_("ربط الحساب"))


class ChildTopupForm(FlaskForm):
    """AZ-P3-15: طلب شحن محفظة ابن — طلب فقط، لا رصيد قبل اعتماد إداري."""

    amount = StringField(
        _("مبلغ الشحن"),
        validators=[DataRequired()],
        render_kw={"inputmode": "decimal", "placeholder": "100.00"},
    )
    note = StringField(_("ملاحظة"))
    submit = SubmitField(_("إرسال طلب الشحن"))

    @property
    def amount_decimal(self) -> Decimal | None:
        try:
            return Decimal((self.amount.data or "").strip())
        except (ValueError, ArithmeticError):
            return None
