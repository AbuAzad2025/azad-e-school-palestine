"""مسارات التقويم الأكاديمي"""

from app.core.permissions import role_required
from app.models.user import UserRole
from app.services.calendar import create_event, delete_event, list_events
from flask import abort, flash, redirect, render_template, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import EventForm


@bp.get("/<int:school_id>")
@login_required
@role_required(UserRole.school_admin, UserRole.super_admin)
def index(school_id):
    from app.core.tenancy import get_school_or_404

    get_school_or_404(school_id)
    events = list_events(school_id)
    return render_template(
        "calendar/index.html",
        school_id=school_id,
        events=events,
        form=EventForm(),
        event_types=[
            ("term_start", _("بداية فصل")),
            ("term_end", _("نهاية فصل")),
            ("exam_period", _("فترة امتحانات")),
            ("enrollment", _("فترة التسجيل")),
            ("holiday", _("إجازة")),
        ],
    )


@bp.post("/<int:school_id>/events")
@login_required
@role_required(UserRole.school_admin, UserRole.super_admin)
def event_create(school_id):
    from app.core.tenancy import get_school_or_404

    get_school_or_404(school_id)
    form = EventForm()
    if form.validate_on_submit():
        event, error = create_event(
            school_id=school_id,
            title=form.title.data,
            event_type=form.event_type.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
        )
        if error:
            flash(_(error), "danger")
        elif event is not None:
            flash(_("أُضيف الحدث."), "success")
    return redirect(url_for("calendar.index", school_id=school_id))


@bp.post("/events/<int:event_id>/delete")
@login_required
@role_required(UserRole.school_admin, UserRole.super_admin)
def event_delete(event_id):
    from app.core.tenancy import current_school_id
    from app.models.calendar import AcademicEvent

    event = AcademicEvent.query.get_or_404(event_id)
    # school_admin can only delete events in their own school
    if current_user.role == UserRole.school_admin:
        if event.school_id != current_school_id():
            abort(403)
    ok, error = delete_event(event_id)
    if error:
        flash(_(error), "danger")
    else:
        flash(_("حُذف الحدث."), "success")
    return redirect(url_for("calendar.index", school_id=event.school_id))
