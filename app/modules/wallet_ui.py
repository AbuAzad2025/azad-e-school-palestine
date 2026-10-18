"""واجهة «محفظتي» — صفحة رصيد وسجل حركات للمستخدم (AZ-P3-14).

فجوة الملخّص التنفيذي رقم 5 في docs/STAKEHOLDER_GAP_ANALYSIS.md: الرصيد والسجل
كانا عبر API حصراً. هذه الواجهة تستهلك ``wallet_service`` وحده — وبالتحديد
``user_ledger_page`` المصدر الوسيط الذي تشاركه أيضاً واجهة «محفظة الابن»
(AZ-P3-15) — فلا استعلام مالي جديد خارج الخدمة، ولا تكرار تسميات الاتجاه
والنوع بين الواجهتين. ولي الأمر يُغطّى في AZ-P3-15 عبر صفحات الأسرة
المستهدفة بالابن، لا هنا.
"""

from __future__ import annotations

from app.core.i18n import _
from app.core.permissions import role_required
from app.models.user import UserRole
from app.services import wallet_service
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

bp = Blueprint("wallet_ui", __name__)

_PER_PAGE = 10


@bp.get("/wallet")
@role_required(UserRole.student, UserRole.teacher)
def my_wallet():
    """«محفظتي»: الرصيد الحالي + سجل الحركات المكتملة بترقيم صفحات."""
    school_id = getattr(current_user, "school_id", None)
    if not school_id:
        flash(_("لا توجد مدرسة نشطة لحسابك لعرض محفظتها."), "error")
        return redirect(url_for("auth.dashboard"))

    page = max(request.args.get("page", 1, type=int) or 1, 1)
    ledger = wallet_service.user_ledger_page(school_id, current_user.id, page=page, per_page=_PER_PAGE)
    if ledger is None:
        # حالة الفراغ الصريحة — لا أصفار مضلّلة (معيار القبول 2)
        return render_template("wallet/index.html", wallet=None)

    if page > ledger["pages"]:
        abort(404)
    return render_template(
        "wallet/index.html",
        wallet=ledger["wallet"],
        summary=ledger["summary"],
        rows=ledger["rows"],
        page=ledger["page"],
        pages=ledger["pages"],
        has_next=ledger["has_next"],
        has_prev=ledger["has_prev"],
    )
