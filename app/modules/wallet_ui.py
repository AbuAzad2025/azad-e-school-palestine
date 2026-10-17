"""واجهة «محفظتي» — صفحة رصيد وسجل حركات للمستخدم (AZ-P3-14).

فجوة الملخّص التنفيذي رقم 5 في docs/STAKEHOLDER_GAP_ANALYSIS.md: الرصيد والسجل
كانا عبر API حصراً. هذه الواجهة تستهلك ``wallet_service`` وحده (DRY — لا
استعلام مالي جديد خارجها)، وتُقيَّد بدوري الطالب والمعلم + super_admin عبر
``role_required``. ولي الأمر يُغطّى في AZ-P3-15 عبر صفحات الأسرة المستهدفة
بالابن، لا هنا.
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import _
from app.core.permissions import role_required
from app.models.user import UserRole
from app.services import wallet_service
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

bp = Blueprint("wallet_ui", __name__)

_PER_PAGE = 10

# تسميات عربية لأنواع قيود الدفتر (مصدر واحد — القالب يعرض ما تُمرَّره فقط)
_TX_TYPE_LABELS: dict[str, str] = {
    wallet_service.TX_TRANSFER: _("تحويل بين حسابين"),
    wallet_service.TX_TUTOR_COMMISSION: _("عمولة المنصة"),
    wallet_service.TX_TUTOR_PAYOUT: _("سحب أرباح"),
    wallet_service.TX_SUBSCRIPTION_CREDIT: _("فائض اشتراك"),
    wallet_service.TX_ADMIN_ADJUSTMENT: _("إيداع إداري"),
    wallet_service.TX_REFUND: _("استرداد"),
    wallet_service.TX_REVERSAL: _("عكس حركة"),
}

_DIRECTION_LABELS = {
    "in": _("وارِد"),
    "out": _("صارِد"),
}


def _decorate(rows: list[Any], wallet_id: int | None) -> list[dict]:
    """حوّل صفوف الدفتر إلى عناصر عرض: اتجاه + تسمية عربية للنوع + تاريخ."""
    items = []
    for t in rows:
        direction = "out" if wallet_id is not None and t.source_wallet_id == wallet_id else "in"
        items.append(
            {
                "id": t.id,
                "amount": t.amount,
                "direction": direction,
                "direction_label": _DIRECTION_LABELS[direction],
                "type_label": _TX_TYPE_LABELS.get(t.transaction_type, t.transaction_type),
                "description": t.description,
                "created_at": t.created_at,
            }
        )
    return items


@bp.get("/wallet")
@role_required(UserRole.student, UserRole.teacher)
def my_wallet():
    """«محفظتي»: الرصيد الحالي + سجل الحركات المكتملة بترقيم صفحات."""
    school_id = getattr(current_user, "school_id", None)
    if not school_id:
        flash(_("لا توجد مدرسة نشطة لحسابك لعرض محفظتها."), "error")
        return redirect(url_for("auth.dashboard"))

    wallet = wallet_service.find_wallet(school_id, current_user.id)
    if wallet is None:
        # حالة الفراغ الصريحة — لا أصفار مضلّلة (معيار القبول 2)
        return render_template(
            "wallet/index.html", wallet=None, rows=[], page=1, pages=1, has_next=False, has_prev=False
        )

    summary = wallet_service.get_wallet_summary(school_id, current_user.id)
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    rows = wallet_service.get_transaction_history(
        school_id, current_user.id, limit=_PER_PAGE, offset=(page - 1) * _PER_PAGE
    )
    pages = max((summary["transaction_count"] + _PER_PAGE - 1) // _PER_PAGE, 1)
    if page > pages:
        abort(404)
    return render_template(
        "wallet/index.html",
        wallet=wallet,
        summary=summary,
        rows=_decorate(rows, wallet.id),
        page=page,
        pages=pages,
        has_next=page < pages,
        has_prev=page > 1,
    )
