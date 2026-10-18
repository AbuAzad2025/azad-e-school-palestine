"""مسارات روابط الأسرة"""

from app.core.permissions import parent_of_required, role_required
from app.models.user import UserRole
from app.services.family import billing_by_student, generate_link_code, link_parent, list_children, remove_link
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import ChildTopupForm, LinkCodeForm


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


# ═══════════════════════════════════════════════════════════════════════════
# AZ-P3-15 — محفظة الابن: عرض للربط، وشحن بطلب يمرّ بالاعتماد الإداري
# ═══════════════════════════════════════════════════════════════════════════
# العرض يستهلك wallet_service.user_ledger_page — نفس المصدر الذي تستهلكه
# واجهة «محفظتي» — فلا استعلام مالي جديد خارج الخدمة. والشحن ليس إثراءً
# مباشراً: يُنشئ طلباً معلّقاً تعتمده الإدارة في wallet_service.review_topup
# فلا رصيد بلا قرار إداري، وهوية الدافع محفوظة على صف الطلب نفسه.


def _child_and_school(student_id: int):
    """الابن الواقعي + مدرسته بشرط تطابقها مع مدرسة ولي الأمر (حدّ التينانت المالي)."""
    from app.extensions import db
    from app.models.user import User

    child = db.session.get(User, student_id)
    if child is None:
        abort(404)
    child_school_id = getattr(child, "school_id", None)
    parent_school_id = getattr(current_user, "school_id", None)
    if not child_school_id or not parent_school_id or child_school_id != parent_school_id:
        abort(403)
    return child, child_school_id


@bp.get("/children/<int:student_id>/wallet")
@parent_of_required
def child_wallet(student_id):
    from app.services import wallet_service

    child, school_id = _child_and_school(student_id)
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    ledger = wallet_service.user_ledger_page(school_id, child.id, page=page, per_page=10)
    if ledger is not None and page > ledger["pages"]:
        abort(404)
    topups = wallet_service.list_child_topups(school_id, current_user.id, child.id)
    return render_template(
        "family/child_wallet.html",
        student_id=student_id,
        child=child,
        ledger=ledger,
        topups=topups,
        topup_form=ChildTopupForm(),
    )


@bp.post("/children/<int:student_id>/wallet/topup")
@parent_of_required
def child_topup(student_id):
    from app.services import wallet_service

    form = ChildTopupForm()
    child, school_id = _child_and_school(student_id)
    if not form.validate_on_submit():
        flash(_("تحقق من بيانات النموذج قبل الإرسال."), "danger")
        return redirect(url_for("family.child_wallet", student_id=student_id))
    amount = form.amount_decimal
    if amount is None:
        flash(_("المبلغ غير صالح — أدخل رقماً موجباً."), "danger")
        return redirect(url_for("family.child_wallet", student_id=student_id))
    _created, error = wallet_service.request_topup(
        school_id=school_id,
        parent_id=current_user.id,
        child_user_id=child.id,
        amount=amount,
        note=form.note.data or "",
    )
    if error:
        flash(_(error), "danger")
    else:
        flash(_("تم إرسال طلب الشحن — بانتظار اعتماد إدارة المدرسة."), "success")
    return redirect(url_for("family.child_wallet", student_id=student_id))
