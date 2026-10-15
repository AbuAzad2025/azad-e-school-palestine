from app.core.permissions import role_required
from app.models.billing import Subscription
from app.models.user import UserRole
from app.services.billing import list_subscriptions
from app.services.individual import get_public_classes, get_student_classes, subscribe_to_class
from flask import flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp


@bp.route("/courses")
@login_required
@role_required(UserRole.student)
def my_courses():
    """AZ-P0-01: الاشتراكات المعلّقة (بانتظار الدفع) ظاهرة في نفس الصفحة —

    كانت ``get_student_classes`` تعيد العضويات الفعّالة فلا يرى الطالب طلب
    الدفع أصلاً، ولا زر يقوده لما يفعّل الكورس.
    """
    memberships = get_student_classes(current_user.id)
    pending_subs = list_subscriptions(user_id=current_user.id, status="pending")
    return render_template("individual/dashboard.html", memberships=memberships, pending_subs=pending_subs)


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
@role_required(UserRole.student)
def subscribe(class_id):
    error = subscribe_to_class(current_user.id, class_id)
    if error:
        flash(_(error), "danger")
    elif Subscription.query.filter_by(user_id=current_user.id, class_id=class_id, status="pending").first() is not None:
        # AZ-P0-01: كورس مدفوع — رسالة التعامل الحقيقية لا رسالة الوصول الفوري
        flash(_("تم إنشاء اشتراكك وهو بانتظار الدفع — أكمل الدفع لتفتح الكورس."), "warning")
    else:
        flash(_("تم الاشتراك بنجاح! يمكنك الآن الوصول إلى محتوى الكورس."), "success")
    return redirect(url_for("individual.my_courses"))
