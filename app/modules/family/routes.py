"""مسارات روابط الأسرة"""

from app.core.permissions import role_required
from app.models.user import UserRole
from app.services.family import generate_link_code, link_parent, list_children, remove_link
from flask import abort, flash, redirect, render_template, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import LinkCodeForm


@bp.get("/")
@login_required
@role_required(UserRole.parent)
def index():
    children = list_children(current_user.id)
    return render_template("family/index.html", children=children, link_form=LinkCodeForm())


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
@login_required
@role_required(UserRole.parent)
def child_progress(student_id):
    from app.services.family import is_parent_of

    if not is_parent_of(current_user.id, student_id):
        abort(403)

    from app.models.class_room import ClassMember

    memberships = ClassMember.query.filter_by(user_id=student_id, status="active").all()
    return render_template("family/child_progress.html", student_id=student_id, memberships=memberships)


@bp.get("/children/<int:student_id>/grades")
@login_required
@role_required(UserRole.parent)
def child_grades(student_id):
    from app.services.family import is_parent_of

    if not is_parent_of(current_user.id, student_id):
        abort(403)

    from app.models.class_room import ClassMember

    memberships = ClassMember.query.filter_by(user_id=student_id, status="active").all()
    return render_template("family/child_grades.html", student_id=student_id, memberships=memberships)
