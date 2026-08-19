from app.models.user import UserRole
from app.services.individual import get_public_classes, get_student_classes, subscribe_to_class
from flask import flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp


@bp.route("/courses")
@login_required
def my_courses():
    if current_user.role not in (UserRole.student, UserRole.super_admin):
        flash(_("هذه الصفحة للطلاب فقط."), "warning")
        return redirect(url_for("auth.dashboard"))
    memberships = get_student_classes(current_user.id)
    return render_template("individual/dashboard.html", memberships=memberships)


@bp.route("/catalog")
@login_required
def catalog():
    subject_id = request.args.get("subject_id", type=int)
    grade_level = request.args.get("grade_level", type=int)
    classes = get_public_classes(subject_id=subject_id, grade_level=grade_level)
    from app.models.school import Subject

    subjects = Subject.query.order_by(Subject.name_ar).all()
    return render_template(
        "individual/course_catalog.html",
        classes=classes,
        subjects=subjects,
        selected_subject=subject_id,
        selected_grade=grade_level,
    )


@bp.route("/catalog/<int:class_id>/subscribe", methods=["POST"])
@login_required
def subscribe(class_id):
    if current_user.role not in (UserRole.student, UserRole.super_admin):
        flash(_("هذه الصفحة للطلاب فقط."), "warning")
        return redirect(url_for("auth.dashboard"))
    error = subscribe_to_class(current_user.id, class_id)
    if error:
        flash(_(error), "danger")
    else:
        flash(_("تم الاشتراك بنجاح! يمكنك الآن الوصول إلى محتوى الكورس."), "success")
    return redirect(url_for("individual.my_courses"))
