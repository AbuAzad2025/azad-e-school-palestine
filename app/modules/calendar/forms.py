"""نماذج التقويم الأكاديمي"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class EventForm(FlaskForm):
    title = StringField(_("العنوان"), validators=[DataRequired(), Length(max=200)])
    event_type = SelectField(
        _("النوع"),
        choices=[
            ("term_start", _("بداية فصل")),
            ("term_end", _("نهاية فصل")),
            ("exam_period", _("فترة امتحانات")),
            ("enrollment", _("فترة التسجيل")),
            ("holiday", _("إجازة")),
        ],
        default="term_start",
    )
    start_date = DateField(_("تاريخ البداية"), validators=[DataRequired()])
    end_date = DateField(_("تاريخ النهاية"), validators=[Optional()])
    submit = SubmitField(_("حفظ الحدث"))
