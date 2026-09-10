"""Wallet REST API — نقاط نهاية المحفظة (إيداع/تحويل/رصيد/سجل).

P1-WALLET-01: REST آمن فوق wallet_service:
    - RBAC صارم: الرصيد/السجل لصاحبه (أو أدمن مدرسته)، التحويل لمصادَق
      من نفس المدرسة، الإيداع/التعديل الإداري لأدمن فقط.
    - Idempotency: كل تحويل يتطلب idempotency_key من العميل (UUID) —
      إعادة الإرسال تعيد نفس النتيجة بلا ازدواج (منطق الخدمة نفسه).
    - عزل تينانتس: school_id من المستخدم أو من الأدمن، ولا تجاوز بين مدارس.
    - OpenAPI: flasgger docstrings لكل نقطة.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.api import api_error, api_response
from app.core.i18n import _
from app.core.logging import get_logger
from app.core.permissions import role_required
from app.models.user import UserRole
from app.services import wallet_service
from flask import Blueprint, request
from flask_login import current_user

logger = get_logger(__name__)

bp = Blueprint("wallet_api", __name__, url_prefix="/api/v1/wallet")


def _school_id_for_admin_scope() -> int | None:
    """نطاق المدرسة: super_admin يمرر ?school_id=، وأدمن المدرسة يُقيَّد بمدرسته."""
    if current_user.role == UserRole.super_admin:
        sid = request.args.get("school_id", type=int)
        return sid
    return getattr(current_user, "school_id", None)


def _parse_amount(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


@bp.get("/balance")
def wallet_balance():
    """رصيد محفظة مستخدم.
    ---
    tags: [Wallet]
    parameters:
      - name: user_id
        in: query
        type: integer
        description: افتراضياً المستخدم الحالي (الأدمن قد يرى غيره)
      - name: school_id
        in: query
        type: integer
        description: للسوبر أدمن فقط
    responses:
      200:
        description: الرصيد الحالي
        schema:
          type: object
          properties:
            data:
              type: object
              properties:
                balance: {type: string, example: "150.00"}
                currency: {type: string, example: ILS}
      403: {description: خارج النطاق}
    """
    target_user_id = request.args.get("user_id", type=int) or current_user.id
    school_id = _school_id_for_admin_scope()

    if target_user_id != current_user.id:
        # مشاهدة محفظة غيرك: أدمن فقط، ونفس المدرسة
        if current_user.role not in (UserRole.super_admin, UserRole.school_admin):
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")
        if school_id is None and current_user.role == UserRole.school_admin:
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")
    elif school_id is None:
        school_id = getattr(current_user, "school_id", None)

    if school_id is None:
        return api_error(_("school_id مطلوب"), 400, "VALIDATION_ERROR")

    balance = wallet_service.get_balance(school_id, target_user_id)
    wallet, _err = wallet_service.get_or_create_wallet(school_id, target_user_id)
    return api_response(
        {"user_id": target_user_id, "balance": str(balance), "currency": wallet.currency if wallet else "ILS"}
    )


@bp.get("/transactions")
def wallet_transactions():
    """سجل حركات المحفظة (مزدوج القيد).
    ---
    tags: [Wallet]
    parameters:
      - name: page
        in: query
        type: integer
      - name: per_page
        in: query
        type: integer
      - name: user_id
        in: query
        type: integer
      - name: school_id
        in: query
        type: integer
        description: للسوبر أدمن فقط
    responses:
      200: {description: قائمة الحركات مرتّبة تنازلياً}
      403: {description: خارج النطاق}
    """
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", 20, type=int), 1), 100)
    target_user_id = request.args.get("user_id", type=int) or current_user.id
    school_id = _school_id_for_admin_scope()

    if target_user_id != current_user.id:
        if current_user.role not in (UserRole.super_admin, UserRole.school_admin):
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")
    elif school_id is None:
        school_id = getattr(current_user, "school_id", None)

    if school_id is None:
        return api_error(_("school_id مطلوب"), 400, "VALIDATION_ERROR")

    rows = wallet_service.get_transaction_history(
        school_id,
        target_user_id,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    items = [
        {
            "id": t.id,
            "amount": str(t.amount),
            "currency": t.currency,
            "type": t.transaction_type,
            "direction": "out" if t.source_wallet and t.source_wallet.user_id == target_user_id else "in",
            "status": t.status,
            "description": t.description,
            "hash": t.transaction_hash,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]
    return api_response(
        items,
        meta={"page": page, "per_page": per_page, "total": len(items), "pages": 1},
    )


@bp.post("/transfers")
@role_required(UserRole.student, UserRole.teacher, UserRole.school_admin, UserRole.super_admin)
def wallet_transfer():
    """تحويل بين محفظتي مستخدمين (مزدوج القيد + idempotency).
    ---
    tags: [Wallet]
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [dest_user_id, amount, idempotency_key]
          properties:
            source_user_id: {type: integer, description: افتراضياً المستخدم الحالي}
            dest_user_id: {type: integer}
            amount: {type: string, example: "50.00"}
            idempotency_key: {type: string, example: "b3f1c9e2-..."}
            description: {type: string}
    responses:
      200: {description: الحركة (الموجودة أو الجديدة)}
      400: {description: تحقق فاشل}
      403: {description: خارج النطاق}
    """
    body = request.get_json(silent=True) or {}
    school_id = getattr(current_user, "school_id", None)
    if school_id is None and current_user.role == UserRole.super_admin:
        school_id = body.get("school_id")
    if school_id is None:
        return api_error(_("school_id مطلوب"), 400, "VALIDATION_ERROR")

    source_user_id = body.get("source_user_id") or current_user.id
    if int(source_user_id) != int(current_user.id) and current_user.role != UserRole.super_admin:
        return api_error(_("لا يمكن التحويل من محفظة غيرك"), 403, "FORBIDDEN")

    dest_user_id = body.get("dest_user_id")
    if not dest_user_id:
        return api_error(_("dest_user_id مطلوب"), 400, "VALIDATION_ERROR")

    amount = _parse_amount(str(body.get("amount") or ""))
    if amount is None:
        return api_error(_("مبلغ غير صالح"), 400, "VALIDATION_ERROR")

    idempotency_key = (body.get("idempotency_key") or "").strip()
    if not idempotency_key:
        return api_error(_("idempotency_key مطلوب (UUID)"), 400, "VALIDATION_ERROR")

    description = (body.get("description") or _("تحويل محفظة")).strip()

    # ضمان وجود محفظتَي الطرفين (بنفس العملة) قبل التحويل
    for uid_ in (int(source_user_id), int(dest_user_id)):
        wallet, w_err = wallet_service.get_or_create_wallet(school_id, uid_)
        if w_err or wallet is None:
            return api_error(w_err or _("تعذر إنشاء المحفظة"), 400, "WALLET_ERROR")

    tx_obj, err = wallet_service.process_transfer(
        school_id=school_id,
        source_user_id=int(source_user_id),
        dest_user_id=int(dest_user_id),
        amount=amount,
        idempotency_key=idempotency_key,
        description=description,
    )
    if err:
        # أخطاء منطقية (رصيد/نفس المستخدم) → 400 بلا كشف داخلي
        return api_error(err, 400, "TRANSFER_FAILED")

    return api_response(
        {
            "id": tx_obj.id,
            "amount": str(tx_obj.amount),
            "currency": tx_obj.currency,
            "type": tx_obj.transaction_type,
            "status": tx_obj.status,
            "hash": tx_obj.transaction_hash,
            "idempotency_key": tx_obj.idempotency_key,
        }
    )


@bp.post("/deposits")
@role_required(UserRole.school_admin, UserRole.super_admin)
def wallet_deposit():
    """إيداع إداري في محفظة مستخدم (admin_adjustment).
    ---
    tags: [Wallet]
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [user_id, amount, idempotency_key]
          properties:
            user_id: {type: integer}
            amount: {type: string, example: "100.00"}
            idempotency_key: {type: string}
            description: {type: string}
    responses:
      200: {description: الحركة المُنشأة}
      400: {description: تحقق فاشل}
    """
    body = request.get_json(silent=True) or {}
    school_id = getattr(current_user, "school_id", None)
    if school_id is None and current_user.role == UserRole.super_admin:
        school_id = body.get("school_id")
    if school_id is None:
        return api_error(_("school_id مطلوب"), 400, "VALIDATION_ERROR")

    target_user_id = body.get("user_id")
    if not target_user_id:
        return api_error(_("user_id مطلوب"), 400, "VALIDATION_ERROR")

    amount = _parse_amount(str(body.get("amount") or ""))
    if amount is None or amount <= 0:
        return api_error(_("مبلغ غير صالح"), 400, "VALIDATION_ERROR")

    idempotency_key = (body.get("idempotency_key") or "").strip()
    if not idempotency_key:
        return api_error(_("idempotency_key مطلوب (UUID)"), 400, "VALIDATION_ERROR")

    # إيداع أدمن = رصيد خارجي يدخل النظام (source NULL) — ضمان وجود المحفظة
    wallet, w_err = wallet_service.get_or_create_wallet(school_id, int(target_user_id))
    if w_err or wallet is None:
        return api_error(w_err or _("تعذر إنشاء المحفظة"), 400, "WALLET_ERROR")

    tx_obj, err = wallet_service.admin_credit(
        school_id=school_id,
        target_user_id=int(target_user_id),
        amount=amount,
        idempotency_key=idempotency_key,
        description=(body.get("description") or _("إيداع إداري")).strip(),
        operator_id=current_user.id,
    )
    if err:
        return api_error(err, 400, "DEPOSIT_FAILED")

    return api_response(
        {
            "id": tx_obj.id,
            "amount": str(tx_obj.amount),
            "status": tx_obj.status,
            "hash": tx_obj.transaction_hash,
        }
    )
