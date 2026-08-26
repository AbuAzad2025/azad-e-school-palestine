"""مسارات موافقات المدرسة — للمشرفين والسوبر أدمن"""

from app.core.permissions import role_required
from app.models.user import UserRole
from app.services.communication import audit
from app.services.school_approvals import (
    approve_user_role_link,
    can_user_approve,
    get_approval_queue_for_user,
    reject_user_role_link,
)
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp


@bp.get("/approvals")
@login_required
@role_required(UserRole.school_admin, UserRole.super_admin)
def approval_queue():
    """صفحة قائمة انتظار الموافقة."""
    links = get_approval_queue_for_user(current_user.id)
    return render_template("school_approvals/queue.html", links=links)


@bp.post("/approvals/<int:link_id>/approve")
@login_required
@role_required(UserRole.school_admin, UserRole.super_admin)
def approve(link_id):
    """الموافقة على طلب انضمام."""

    if not can_user_approve(current_user.id, link_id):
        abort(403)

    success, error = approve_user_role_link(link_id, current_user.id)
    if error:
        flash(error, "danger")
    else:
        flash(_("تم قبول المستخدم بنجاح."), "success")
        audit(
            "school_approval.approve",
            "user_role_links",
            link_id,
            detail={"approver_id": current_user.id},
        )

    return redirect(url_for("school_approvals.approval_queue"))


@bp.post("/approvals/<int:link_id>/reject")
@login_required
@role_required(UserRole.school_admin, UserRole.super_admin)
def reject(link_id):
    """رفض طلب انضمام."""

    if not can_user_approve(current_user.id, link_id):
        abort(403)

    reason = request.form.get("reason", "").strip() or None
    success, error = reject_user_role_link(link_id, current_user.id, reason)
    if error:
        flash(error, "danger")
    else:
        flash(_("تم رفض المستخدم."), "warning")
        audit(
            "school_approval.reject",
            "user_role_links",
            link_id,
            detail={"approver_id": current_user.id},
        )

    return redirect(url_for("school_approvals.approval_queue"))


@bp.get("/admin/approvals")
@login_required
@role_required(UserRole.super_admin)
def super_admin_approval_queue():
    """صفحة قائمة انتظار الموافقة للسوبر أدمن."""
    from app.services.school_approvals import get_pending_approvals_for_super_admin

    links = get_pending_approvals_for_super_admin()
    return render_template("school_approvals/super_admin_queue.html", links=links)
