"""واجهة «محفظتي» — صفحة رصيد وسجل حركات للمستخدم (AZ-P3-14).

فجوة الملخّص التنفيذي رقم 5 في docs/STAKEHOLDER_GAP_ANALYSIS.md: الرصيد والسجل
كانا عبر API حصراً. هذه الواجهة تستهلك ``wallet_service`` وحده — وبالتحديد
``user_ledger_page`` المصدر الوسيط الذي تشاركه أيضاً واجهة «محفظة الابن»
(AZ-P3-15) — فلا استعلام مالي جديد خارج الخدمة، ولا تكرار تسميات الاتجاه
والنوع بين الواجهتين. ولي الأمر يُغطّى في AZ-P3-15 عبر صفحات الأسرة
المستهدفة بالابن، لا هنا.
"""

from __future__ import annotations

import uuid

from app.core.i18n import _
from app.core.permissions import role_required
from app.models.user import UserRole
from app.services import wallet_service
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

bp = Blueprint("wallet_ui", __name__)

_PER_PAGE = 10


@bp.get("/")
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


@bp.get("/family/wallet")
@role_required(UserRole.parent)
def parent_child_wallet():
    """«محفظة الابن»: عرض رصيد وسجل الحركات للابن المرتبط."""
    from app.core.i18n import _
    from app.models.family import FamilyLink
    from app.services.family import list_children
    from app.services.wallet_service import (
        decorate_transactions,
        find_wallet,
        get_balance,
        get_transaction_history,
    )

    # الحصول على قائمة الأبناء النشطين
    children = list_children(current_user.id)

    # إذا تم تحديد ابن معين كمعلمة
    child_id = request.args.get("child_id", type=int)
    school_id = getattr(current_user, "school_id", None)

    if not school_id:
        flash(_("لا توجد مدرسة نشطة لحسابك."), "error")
        return redirect(url_for("auth.dashboard"))

    # إذا لم يتم تحديد ابن، عرض قائمة بالأبناء
    if not child_id:
        return render_template(
            "wallet/parent_family.html",
            children=children,
            _=_,  # gettext
            school_id=school_id,
        )

    # التحقق من أن هذا الابن مرتبط بهذا الوالد
    link = FamilyLink.query.filter_by(parent_id=current_user.id, student_id=child_id, status="active").first()
    if not link:
        flash(_("أنت غير مرتبط بهذا الابن في النظام."), "error")
        return redirect(url_for("wallet_ui.parent_child_wallet"))

    # تجهيز الاسم لعرضه في القالب — الطفل المستعرَض يجب أن يكون ضمن روابطه
    child_name = next(
        (link.student.name_ar for link in children if link.student_id == child_id),
        _("الابن"),
    )

    # الحصول على الرصيد والحركات للمحفظة
    get_balance(school_id, child_id)
    wallet = find_wallet(school_id, child_id)
    transactions = get_transaction_history(school_id, child_id, limit=_PER_PAGE, offset=0)

    if not wallet or not transactions:
        return render_template(
            "wallet/parent_wallet.html",
            wallet=wallet,
            summary={
                "balance": "0.00",
                "total_received": "0.00",
                "total_sent": "0.00",
                "transaction_count": 0,
                "currency": "ILS",
            },
            rows=[],
            child_id=child_id,
            child_name=child_name,
            children=children,
            has_wallet=wallet is not None,
            _=_,  # gettext
            school_id=school_id,
        )

    # تجهيز البيانات للعرض
    summary = (
        wallet_service.get_wallet_summary(school_id, child_id)
        if wallet
        else {
            "balance": "0.00",
            "total_received": "0.00",
            "total_sent": "0.00",
            "transaction_count": 0,
            "currency": "ILS",
        }
    )

    # تمييز اتجاه الحركات بالنسبة للمحفظة
    decorated_rows = decorate_transactions(transactions, wallet.id if wallet else 0)

    return render_template(
        "wallet/parent_wallet.html",
        wallet=wallet,
        summary=summary,
        rows=decorated_rows,
        child_id=child_id,
        child_name=child_name,
        children=children,
        has_wallet=wallet is not None,
        _=_,  # gettext
        school_id=school_id,
    )


@bp.post("/family/wallet/topup")
@role_required(UserRole.parent)
def topup_child():
    """شحن محفظة الابن من ولي الأمر."""
    from decimal import Decimal, InvalidOperation

    from app.core.i18n import _
    from app.services.family import list_children

    children = list_children(current_user.id)
    child_id = request.form.get("child_id", type=int)

    if not child_id or child_id not in {c.student_id for c in children}:
        flash(_("ابن غير محدّد أو غير مرخّص."), "error")
        return redirect(url_for("wallet_ui.parent_child_wallet"))

    school_id = getattr(current_user, "school_id", None)
    if not school_id:
        flash(_("لا توجد مدرسة نشطة لحسابك."), "error")
        return redirect(url_for("auth.dashboard"))

    amount = request.form.get("amount")
    if not amount:
        flash(_("مبلغ مطلوب"), "error")
        return redirect(url_for("wallet_ui.parent_child_wallet", child_id=child_id))

    try:
        amount_dec = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        flash(_("مبلغ غير صالح"), "error")
        return redirect(url_for("wallet_ui.parent_child_wallet", child_id=child_id))

    if amount_dec <= 0:
        flash(_("المبلغ يجب أن يكون أكبر من صفر"), "error")
        return redirect(url_for("wallet_ui.parent_child_wallet", child_id=child_id))

    # ضمان وجود محفظة الابن
    wallet, err = wallet_service.get_or_create_wallet(school_id, child_id)
    if err or wallet is None:
        flash(_("تعذّر تجهيز المحفظة"), "error")
        return redirect(url_for("wallet_ui.parent_child_wallet", child_id=child_id))

    # تطبيق الإيداع الإداري
    tx_obj, err = wallet_service.admin_credit(
        school_id=school_id,
        target_user_id=int(child_id),
        amount=amount_dec,
        idempotency_key=f"parent_topup:{current_user.id}:{child_id}:{uuid.uuid4().hex}",
        description=_("شحن من ولي الأمر"),
        operator_id=current_user.id,
    )
    if err:
        flash(_(err), "error")
        return redirect(url_for("wallet_ui.parent_child_wallet", child_id=child_id))

    flash(_("تم شحن المحفظة بمبلغ %(amount)s", amount=amount_dec), "success")
    return redirect(url_for("wallet_ui.parent_child_wallet", child_id=child_id))
