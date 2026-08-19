"""مسارات صفحة التواصل"""

from app.core.db import tx
from app.extensions import db
from app.models.communication import ContactMessage
from flask import flash, redirect, render_template, url_for
from flask_babel import _

from . import bp
from .forms import ContactForm


@bp.get("/")
def contact():
    """صفحة نموذج التواصل"""
    return render_template("contact/contact.html", form=ContactForm())


@bp.post("/")
def contact_submit():
    """إرسال نموذج التواصل"""
    form = ContactForm()
    if form.validate_on_submit():

        def _save():
            msg = ContactMessage(
                name=form.name.data,
                email=form.email.data,
                phone=form.phone.data,
                subject=form.subject.data,
                message=form.message.data,
            )
            db.session.add(msg)
            return msg

        tx(_save)
        flash(_("شكراً لتواصلكم! سنرد عليكم قريباً."), "success")
        return redirect(url_for("contact.contact"))
    return render_template("contact/contact.html", form=form)
