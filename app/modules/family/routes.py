"""مسارات روابط الأسرة"""

from app.core.permissions import parent_of_required, role_required
from app.models.user import UserRole
from app.services.family import billing_by_student, generate_link_code, link_parent, list_children, remove_link
from flask import flash, redirect, render_template, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import LinkCodeForm


@bp.get("/")
@login_required
@role_required(UserRole.parent)
def index():
    children = list_children(current_user.id)
    # AZ-P0-03: كشف حساب الأسرة — لكل ابن اشتراكاته وحالتها والمتبقي عليها.
    fees_by_student = billing_by_student(current_user.id)
    return render_template(
        "family/index.html",
        children=children,
        fees_by_student=fees_by_student,
        link_form=LinkCodeForm(),
    )


@bp.post("/link")
@login_required
@role_required(UserRole.parent)
def do_link():
    form = LinkCodeForm()
    if form.validate_on_submit():
        link, error = link_parent(current_user.id, form.code.data)
        if error:
            flash(_(error), "danger")
        elif link is not None:
            flash(_("تم ربط الحساب بنجاح."), "success")
    return redirect(url_for("family.index"))


@bp.post("/link/<int:link_id>/remove")
@login_required
@role_required(UserRole.parent)
def do_remove(link_id):
    ok, error = remove_link(link_id, current_user.id)
    if error:
        flash(_(error), "danger")
    else:
        flash(_("تم إلغاء الربط."), "success")
    return redirect(url_for("family.index"))


@bp.get("/generate")
@login_required
@role_required(UserRole.student)
def generate_code():
    code, error = generate_link_code(current_user.id)
    if error:
        flash(_(error), "danger")
        return redirect(url_for("auth.dashboard"))
    return render_template("family/generate_code.html", code=code)


@bp.get("/children/<int:student_id>/progress")
@parent_of_required
def child_progress(student_id):
    # AZ-P2-11: إنجاز الدروس + المعدل + الحضور لكل صف (استعلامات مجمّعة).
    from app.services.family import child_progress_summary

    progress_rows = child_progress_summary(student_id)
    return render_template(
        "family/child_progress.html",
        student_id=student_id,
        progress_rows=progress_rows,
    )


@bp.get("/children/<int:student_id>/grades")
@parent_of_required
def child_grades(student_id):
    from app.models.class_room import ClassMember

    memberships = ClassMember.query.filter_by(user_id=student_id, status="active").all()
    return render_template("family/child_grades.html", student_id=student_id, memberships=memberships)
