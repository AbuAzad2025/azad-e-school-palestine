"""نماذج الدروس الخصوصية"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import DateTimeLocalField, DecimalField, HiddenField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class TutorProfileForm(FlaskForm):
    subject = StringField(_("المادة التي تدرّسها"), validators=[DataRequired(), Length(max=120)])
    price_hour = DecimalField(_("سعر الساعة"), validators=[Optional()], places=2)
    price_session = DecimalField(_("سعر الجلسة"), validators=[Optional()], places=2)
    mode = SelectField(
        _("طريقة الجلسة"),
        choices=[("both", _("أونلاين وحضوري")), ("online", _("أونلاين")), ("offline", _("حضوري"))],
        default="both",
    )
    bio = TextAreaField(_("نبذة عنك"), validators=[Optional(), Length(max=1000)])
    submit = SubmitField(_("حفظ الملف"))


class BookingForm(FlaskForm):
    subject = StringField(_("المادة المطلوبة"), validators=[DataRequired(), Length(max=120)])
    preferred_time = DateTimeLocalField(_("الوقت المفضّل"), validators=[DataRequired()], format="%Y-%m-%dT%H:%M")
    mode = SelectField(
        _("الطريقة"),
        choices=[("online", _("أونلاين")), ("offline", _("حضوري"))],
        default="online",
    )
    price_quote = DecimalField(_("السعر المقترح"), validators=[Optional()], places=2)
    note = TextAreaField(_("ملاحظات"), validators=[Optional(), Length(max=1000)])
    submit = SubmitField(_("إرسال طلب الحجز"))


class SessionForm(FlaskForm):
    scheduled_at = DateTimeLocalField(_("موعد الجلسة"), validators=[DataRequired()], format="%Y-%m-%dT%H:%M")
    duration_min = DecimalField(_("المدة (دقائق)"), validators=[Optional()])
    price = DecimalField(_("السعر"), validators=[Optional()], places=2)
    mode = SelectField(
        _("الطريقة"),
        choices=[("online", _("أونلاين")), ("offline", _("حضوري"))],
        default="online",
    )
    online_link = StringField(_("رابط الاجتماع"), validators=[Optional(), Length(max=500)])
    location = StringField(_("المكان الحضوري"), validators=[Optional(), Length(max=300)])
    submit = SubmitField(_("تأكيد الجلسة"))


class PaySessionForm(FlaskForm):
    session_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField(_("تأكيد استلام الدفع"))
