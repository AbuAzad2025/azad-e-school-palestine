"""نماذج روابط الأسرة"""

from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LinkCodeForm(FlaskForm):
    code = StringField(_("رمز الربط"), validators=[DataRequired(), Length(min=6, max=12)])
    submit = SubmitField(_("ربط الحساب"))
