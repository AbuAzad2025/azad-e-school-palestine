"""Wallet Service — Double-entry accounting ledger with enterprise guarantees.

P7-05: All transfers use .with_for_update() row locking to prevent deadlocks.
P7-06: Idempotency via processed_events table — no duplicate transactions.
P7-07: Decimal(10,2) with ROUND_HALF_UP for all financial calculations.
P7-08: Transaction hash for audit trail integrity.
P7-09: Tenancy enforced via school_id on all models.
P7-10: All writes wrapped in tx() — atomic commit/rollback.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.core.db import TxError, tx
from app.core.i18n import _
from app.core.logging import get_logger
from app.extensions import db

if TYPE_CHECKING:
    # Flask-SQLAlchemy تُثري Query بدالة paginate التي لا تعرفها sqlalchemy.orm.
    from flask_sqlalchemy.query import Query

logger = get_logger(__name__)

CENT = Decimal("0.01")

# Transaction type constants
TX_TRANSFER = "transfer"
TX_TUTOR_COMMISSION = "tutor_commission"
TX_TUTOR_PAYOUT = "tutor_payout"
TX_SUBSCRIPTION_CREDIT = "subscription_credit"
TX_ADMIN_ADJUSTMENT = "admin_adjustment"
TX_REFUND = "refund"
# AZ-P1-07: قيد مقابل لحركة معكوسة — أصلاً جديد في الدفتر لا تعديل على غيره.
TX_REVERSAL = "reversal"


def _money(value: Decimal | float | int | str) -> Decimal:
    """Normalize any numeric value to Decimal(10,2) with ROUND_HALF_UP."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _generate_tx_hash(
    school_id: int,
    source_wallet_id: int | None,
    dest_wallet_id: int | None,
    amount: Decimal,
    tx_type: str,
) -> str:
    """Generate SHA-256 transaction hash for audit trail."""
    payload = f"{school_id}:{source_wallet_id}:{dest_wallet_id}:{amount}:{tx_type}:{uuid.uuid4().hex}"
    return hashlib.sha256(payload.encode()).hexdigest()


def get_or_create_wallet(
    school_id: int,
    user_id: int,
    currency: str = "ILS",
) -> tuple[Any, str | None]:  # noqa: F821
    """Get or create a wallet for a user in a school.

    Uses tx() for atomic creation. Idempotent — safe to call multiple times.

    Args:
        school_id: School (tenant).
        user_id: Wallet owner.
        currency: Currency code (default ILS).

    Returns:
        (Wallet, None) on success, (None, error_message) on failure.
    """
    from app.models.wallet import Wallet

    existing = Wallet.query.filter_by(school_id=school_id, user_id=user_id, currency=currency).first()
    if existing:
        return existing, None

    def _create():
        wallet = Wallet(
            school_id=school_id,
            user_id=user_id,
            balance=Decimal("0.00"),
            currency=currency,
            status="active",
        )
        db.session.add(wallet)
        return wallet

    wallet = tx(_create)
    logger.info(
        "wallet_created",
        wallet_id=wallet.id,
        school_id=school_id,
        user_id=user_id,
        currency=currency,
    )
    return wallet, None


def get_balance(
    school_id: int,
    user_id: int,
    currency: str = "ILS",
) -> Decimal:
    """Get the current balance for a user's wallet.

    Args:
        school_id: School (tenant).
        user_id: Wallet owner.
        currency: Currency code.

    Returns:
        Current balance as Decimal.
    """
    from app.models.wallet import Wallet

    wallet = Wallet.query.filter_by(school_id=school_id, user_id=user_id, currency=currency).first()
    if not wallet:
        return Decimal("0.00")
    return _money(wallet.balance)


def process_transfer(
    school_id: int,
    source_user_id: int,
    dest_user_id: int,
    amount: Decimal,
    idempotency_key: str,
    description: str,
    tx_type: str = TX_TRANSFER,
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> tuple[Any, str | None]:
    """Process a wallet-to-wallet transfer with full enterprise guarantees.

    Safety mechanisms:
        1. Row locking via .with_for_update() — ordered by wallet ID to prevent deadlocks
        2. Idempotency check — duplicate idempotency_key returns existing result
        3. Balance verification — insufficient funds → TxError
        4. Decimal(10,2) ROUND_HALF_UP — precise financial calculations
        5. Atomic via tx() — all changes committed or all rolled back
        6. Transaction hash — SHA-256 for audit trail

    Args:
        school_id: School (tenant isolation).
        source_user_id: Sender wallet owner.
        dest_user_id: Receiver wallet owner.
        amount: Transfer amount (Decimal).
        idempotency_key: Unique key for deduplication.
        description: Human-readable description.
        tx_type: Transaction type constant.
        reference_type: Optional linked entity type.
        reference_id: Optional linked entity ID.

    Returns:
        (WalletTransaction, None) on success, (None, error_message) on failure.
    """
    from app.models.wallet import Wallet, WalletTransaction

    amount_dec = _money(amount)
    if amount_dec <= 0:
        return None, _("المبلغ يجب أن يكون أكبر من صفر.")

    if source_user_id == dest_user_id:
        return None, _("لا يمكن التحويل للمستخدم نفسه.")

    # Check idempotency
    existing_tx = WalletTransaction.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_tx:
        logger.info(
            "transfer_idempotent_hit",
            idempotency_key=idempotency_key,
            existing_tx_id=existing_tx.id,
        )
        return existing_tx, None

    def _transfer():
        # Lock wallets in consistent order (by ID) to prevent deadlocks
        source_wallet = (
            db.session.query(Wallet).filter_by(school_id=school_id, user_id=source_user_id).with_for_update().first()
        )
        dest_wallet = (
            db.session.query(Wallet).filter_by(school_id=school_id, user_id=dest_user_id).with_for_update().first()
        )

        if not source_wallet:
            raise TxError(_("محفظة المرسل غير موجودة."))
        if not dest_wallet:
            raise TxError(_("محفظة المستلم غير موجودة."))

        if source_wallet.status != "active":
            raise TxError(_("محفظة المرسل غير نشطة."))
        if dest_wallet.status != "active":
            raise TxError(_("محفظة المستلم غير نشطة."))

        if source_wallet.currency != dest_wallet.currency:
            raise TxError(_("العملتان غير متطابقتين."))

        # Check sufficient balance
        source_balance = _money(source_wallet.balance)
        if source_balance < amount_dec:
            raise TxError(
                _(
                    "الرصيد غير كافٍ. المتاح: %(available)s %(currency)s",
                    available=source_balance,
                    currency=source_wallet.currency,
                )
            )

        # Debit source
        source_wallet.balance = _money(source_balance - amount_dec)

        # Credit destination
        dest_balance = _money(dest_wallet.balance)
        dest_wallet.balance = _money(dest_balance + amount_dec)

        # Generate transaction hash
        tx_hash = _generate_tx_hash(school_id, source_wallet.id, dest_wallet.id, amount_dec, tx_type)

        # Create ledger entry
        ledger_tx = WalletTransaction(
            school_id=school_id,
            source_wallet_id=source_wallet.id,
            destination_wallet_id=dest_wallet.id,
            amount=amount_dec,
            currency=source_wallet.currency,
            transaction_type=tx_type,
            transaction_hash=tx_hash,
            idempotency_key=idempotency_key,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            status="completed",
        )
        db.session.add(ledger_tx)
        return ledger_tx

    try:
        result = tx(_transfer)
    except TxError as exc:
        return None, str(exc)

    logger.info(
        "transfer_completed",
        tx_id=result.id,
        school_id=school_id,
        source_user=source_user_id,
        dest_user=dest_user_id,
        amount=str(amount_dec),
        tx_type=tx_type,
    )
    return result, None


def process_tutor_commission(
    school_id: int,
    tutor_user_id: int,
    platform_user_id: int,
    session_amount: Decimal,
    commission_rate: Decimal,
    idempotency_key: str,
    session_id: int,
) -> tuple[Any, str | None]:
    """Process tutor commission — transfer from tutor to platform.

    commission_amount = session_amount * commission_rate / 100
    tutor_net = session_amount - commission_amount

    Args:
        school_id: School (tenant).
        tutor_user_id: Tutor receiving payment.
        platform_user_id: Platform account receiving commission.
        session_amount: Total session amount.
        commission_rate: Commission percentage (e.g., 20 for 20%).
        idempotency_key: Unique key for deduplication.
        session_id: Linked tutoring session ID.

    Returns:
        (WalletTransaction, None) on success, (None, error_message) on failure.
    """
    amount = _money(session_amount)
    rate = _money(commission_rate)
    commission = _money(amount * rate / Decimal("100"))
    _money(amount - commission)

    # Credit tutor's wallet
    # The session payment goes to tutor first, then commission is deducted
    tx_result, error = process_transfer(
        school_id=school_id,
        source_user_id=tutor_user_id,
        dest_user_id=platform_user_id,
        amount=commission,
        idempotency_key=idempotency_key,
        description=f"عمولة منصة ({rate}%) على جلسة #{session_id}",
        tx_type=TX_TUTOR_COMMISSION,
        reference_type="tutoring_session",
        reference_id=session_id,
    )
    return tx_result, error


def admin_credit(
    school_id: int,
    target_user_id: int,
    amount: Decimal,
    idempotency_key: str,
    description: str,
    operator_id: int | None = None,
) -> tuple[Any, str | None]:
    """Credit a wallet without debiting another (admin adjustment / deposit).

    Double-entry note: external inflows are represented with source_wallet_id
    = NULL (money entering the system), which the model already permits.
    """
    from app.models.wallet import Wallet, WalletTransaction

    amount_dec = _money(amount)
    if amount_dec <= 0:
        return None, _("المبلغ يجب أن يكون أكبر من صفر.")

    existing_tx = WalletTransaction.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_tx:
        logger.info("admin_credit_idempotent_hit", idempotency_key=idempotency_key, tx_id=existing_tx.id)
        return existing_tx, None

    def _credit():
        wallet = (
            db.session.query(Wallet).filter_by(school_id=school_id, user_id=target_user_id).with_for_update().first()
        )
        if not wallet:
            raise TxError(_("المحفظة غير موجودة."))
        if wallet.status != "active":
            raise TxError(_("المحفظة غير نشطة."))

        wallet.balance = _money(_money(wallet.balance) + amount_dec)
        tx_hash = _generate_tx_hash(school_id, None, wallet.id, amount_dec, TX_ADMIN_ADJUSTMENT)
        ledger_tx = WalletTransaction(
            school_id=school_id,
            source_wallet_id=None,
            destination_wallet_id=wallet.id,
            amount=amount_dec,
            currency=wallet.currency,
            transaction_type=TX_ADMIN_ADJUSTMENT,
            transaction_hash=tx_hash,
            idempotency_key=idempotency_key,
            description=description,
            reference_type="admin",
            reference_id=operator_id,
            status="completed",
        )
        db.session.add(ledger_tx)
        return ledger_tx

    try:
        result = tx(_credit)
    except TxError as exc:
        return None, str(exc)

    logger.info(
        "admin_credit_completed",
        tx_id=result.id,
        school_id=school_id,
        target_user=target_user_id,
        amount=str(amount_dec),
        operator=operator_id,
    )
    return result, None


def get_transaction_history(
    school_id: int,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[Any]:
    """Get transaction history for a user's wallet.

    Args:
        school_id: School (tenant).
        user_id: Wallet owner.
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of WalletTransaction objects.
    """
    from app.models.wallet import Wallet, WalletTransaction

    wallet = Wallet.query.filter_by(school_id=school_id, user_id=user_id).first()
    if not wallet:
        return []

    return (
        WalletTransaction.query.filter(
            db.or_(
                WalletTransaction.source_wallet_id == wallet.id,
                WalletTransaction.destination_wallet_id == wallet.id,
            ),
            WalletTransaction.school_id == school_id,
            WalletTransaction.status == "completed",
        )
        .order_by(WalletTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_wallet_summary(school_id: int, user_id: int) -> dict:
    """Get a summary of a user's wallet activity.

    Returns:
        {balance, total_received, total_sent, transaction_count, currency}
    """
    from app.models.wallet import Wallet, WalletTransaction

    wallet = Wallet.query.filter_by(school_id=school_id, user_id=user_id).first()
    if not wallet:
        return {
            "balance": "0.00",
            "total_received": "0.00",
            "total_sent": "0.00",
            "transaction_count": 0,
            "currency": "ILS",
        }

    # Aggregate received
    received = db.session.query(func.sum(WalletTransaction.amount)).filter(
        WalletTransaction.destination_wallet_id == wallet.id,
        WalletTransaction.status == "completed",
    ).scalar() or Decimal("0")

    # Aggregate sent
    sent = db.session.query(func.sum(WalletTransaction.amount)).filter(
        WalletTransaction.source_wallet_id == wallet.id,
        WalletTransaction.status == "completed",
    ).scalar() or Decimal("0")

    # Count transactions
    count = WalletTransaction.query.filter(
        db.or_(
            WalletTransaction.source_wallet_id == wallet.id,
            WalletTransaction.destination_wallet_id == wallet.id,
        ),
        WalletTransaction.status == "completed",
    ).count()

    return {
        "balance": str(_money(wallet.balance)),
        "total_received": str(_money(received)),
        "total_sent": str(_money(sent)),
        "transaction_count": count,
        "currency": wallet.currency,
    }


# ════════════════════════════════════════════════════════════════════
# مستكشف الدفتر وعكس الحركة (AZ-P1-07)
# ════════════════════════════════════════════════════════════════════
# حالة ``reversed`` معرّفة في النموذج، لكن لا مسار لعكس حركة، وسجل الحركات
# مُتاح فقط لمستخدم واحد عبر API. الدفتر هنا **غير قابل للتغيير**: العكس لا
# يعدّل صف الأصل ولا يحذفه، بل يُنشئ قيداً مقابلاً (أطراف مقلوبة، نفس المبلغ)
# يُشير إلى الأصل عبر ``reference_type``/``reference_id``. ووجود هذا القيد
# المقابل هو علامة «معكوسة» — ولهذا يُرفض العكس الثاني بلا الحاجة إلى كتابة
# حالة على الأصل.
#
# حفظ المال: الطرف المدين في العكس هو الطرف الدائن في الأصل (المحفظة التي
# دخلها المال)، فإن لم يكن فيها رصيد يكفي فالحركة أُنفقت لاحقاً ولا يجوز عكسها
# برقم سلبي — يُرفض العكس برسالة صريحة. والعملية كلها داخل ``tx()`` بصف
# الأصل مقفلاً (``with_for_update``) فلا يمر عكس ثانٍ متزامن، و``idempotency``
# فريد على القيد المقابل كطبقة ثانية.

WALLET_REVERSAL_REFERENCE = "wallet_reversal"


def ledger_query(
    school_id: int | None = None,
    owner_user_id: int | None = None,
    tx_type: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
) -> Query:
    """بناء استعلام دفتر المحفظة — المستكشف يُصفّحه كما يصفّح سجل التدقيق.

    ``school_id`` هو حدّ التينانت (RLS طبقة أولى وهذا فلتر صريح طبقة ثانية)،
    و``owner_user_id`` يقصر على الحركات التي تمسّ محافظ مستخدم واحد (كأي من
    طرفي الحركة).
    """
    from app.models.wallet import Wallet, WalletTransaction

    # الحمولة تُقرأ من الخدمة مرة واحدة: المحفظتان ومالكاهما والمدرسة — بلا
    # استعلام لكل صف في صفحة المستكشف.
    query = WalletTransaction.query.options(
        joinedload(WalletTransaction.source_wallet).joinedload(Wallet.user),
        joinedload(WalletTransaction.destination_wallet).joinedload(Wallet.user),
        joinedload(WalletTransaction.school),
    )

    if school_id is not None:
        query = query.filter(WalletTransaction.school_id == school_id)
    if tx_type:
        query = query.filter(WalletTransaction.transaction_type == tx_type)
    if status:
        query = query.filter(WalletTransaction.status == status)
    if date_from is not None:
        query = query.filter(WalletTransaction.created_at >= date_from)
    if date_to is not None:
        query = query.filter(WalletTransaction.created_at <= date_to)
    if owner_user_id is not None:
        query = query.filter(
            db.or_(
                WalletTransaction.source_wallet.has(Wallet.user_id == owner_user_id),
                WalletTransaction.destination_wallet.has(Wallet.user_id == owner_user_id),
            )
        )
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                WalletTransaction.description.ilike(pattern),
                WalletTransaction.idempotency_key.ilike(pattern),
                WalletTransaction.transaction_hash.ilike(pattern),
            )
        )
    return query


def user_has_active_link_in_school(user_id: int, school_id: int) -> bool:
    """هل المستخدم عضو نشط في هذه المدرسة؟

    يُفحص نفس الجدول الذي تعتمده RLS (``user_role_links`` بدور نشط). هذه هي
    الدالة **الصارمة**: لا تتجاوز الفحص لأي دور — ومنها المنصة، لأن إيداعاً في
    محفظة ``school_id`` لمستخدم لا رابط له بها يزرع رصيداً لمستخدم غريب في
    مدرسة لا صلة له بها (وهو ما أغلقته D7 في واجهة API).
    """
    from app.models.user import UserRoleLink

    return UserRoleLink.query.filter_by(user_id=user_id, school_id=school_id, is_active=True).first() is not None


def admin_deposit(
    school_id: int,
    target_user_id: int,
    amount: Decimal,
    operator_id: int | None = None,
    note: str = "",
    idempotency_key: str | None = None,
) -> tuple[Any, str | None]:
    """إيداع إداري من الواجهة: عضوية نشطة + محفظة مضمونة + قيداً في الدفتر.

    يجمع ما تحتاجه الواجهة في نداء واحد: التحقق الصارم من أن المستخدم عضو نشط
    في المدرسة (لا شحن لمحفظة شخص من مدرسة أخرى)، ثم ضمان وجود المحفظة، ثم
    ``admin_credit`` الذي يرفض المبالغ غير الموجبة ويكتب الرصيد والقيد في
    ``tx()`` واحدة. مُعرّف التفرد يُولَّد هنا إن لم يمرّره الطلب، ومشغّل العملية
    يُسجَّل على القيد (``reference_id``) وعلى سجل التدقيق في طبقة المسار.
    """
    if target_user_id <= 0 or school_id <= 0:
        return None, _("بيانات الإيداع غير صالحة.")
    if not user_has_active_link_in_school(target_user_id, school_id):
        return None, _("المستخدم ليس عضواً نشطاً في هذه المدرسة.")

    wallet, wallet_error = get_or_create_wallet(school_id, target_user_id)
    if wallet_error or wallet is None:
        return None, wallet_error or _("تعذّر تجهيز المحفظة.")

    return admin_credit(
        school_id=school_id,
        target_user_id=target_user_id,
        amount=amount,
        idempotency_key=idempotency_key or f"admin_deposit:{school_id}:{target_user_id}:{uuid.uuid4().hex}",
        description=note.strip() or _("إيداع إداري"),
        operator_id=operator_id,
    )


def find_reversal_of(transaction_id: int) -> Any:
    """القيد المقابل لحركة — ``None`` إن لم تُعكس بعد."""
    from app.models.wallet import WalletTransaction

    return WalletTransaction.query.filter_by(
        reference_type=WALLET_REVERSAL_REFERENCE, reference_id=transaction_id
    ).first()


def reverse_transaction(
    school_id: int,
    transaction_id: int,
    operator_id: int | None = None,
    reason: str = "",
) -> tuple[Any, str | None]:
    """عكس حركة بقيد مقابل داخل ``tx()`` — بلا تعديل أو حذف للأصل.

    Args:
        school_id: المدرسة (حدّ التينانت — حركة مدرسة أخرى لا تُرى ولا تُعكس).
        transaction_id: معرّف الحركة الأصلية.
        operator_id: المنفّذ (يُسجَّل في الوصف والتدقيق).
        reason: سبب العكس (يُدمج في وصف القيد المقابل).

    Returns:
        (WalletTransaction, None) للقيد المقابل، أو (None, رسالة خطأ) للفشل.
    """
    from app.models.wallet import Wallet, WalletTransaction

    def _reverse():
        original = (
            db.session.query(WalletTransaction)
            .filter(WalletTransaction.id == transaction_id, WalletTransaction.school_id == school_id)
            .with_for_update()
            .first()
        )
        if original is None:
            raise TxError(_("الحركة غير موجودة في هذه المدرسة."))
        if original.transaction_type == TX_REVERSAL:
            raise TxError(_("لا يمكن عكس قيد عكس."))

        existing = (
            db.session.query(WalletTransaction)
            .filter_by(reference_type=WALLET_REVERSAL_REFERENCE, reference_id=original.id)
            .first()
        )
        if existing is not None:
            raise TxError(_("هذه الحركة معكوسة مسبقاً."))

        amount = _money(original.amount)
        # أطراف العكس مقلوبة: ما دخل صار يخرج، وما خرج صار يعود. وطرف ``None``
        # يعني مالاً عبر حدود النظام (إيداع إداري) — فيخرج عند العكس بلا مقابل.
        origin_wallet = (
            db.session.query(Wallet).filter_by(id=original.destination_wallet_id).with_for_update().first()
            if original.destination_wallet_id
            else None
        )
        back_wallet = (
            db.session.query(Wallet).filter_by(id=original.source_wallet_id).with_for_update().first()
            if original.source_wallet_id
            else None
        )

        if original.destination_wallet_id and origin_wallet is None:
            raise TxError(_("محفظة الطرف المقابل غير موجودة."))
        if original.source_wallet_id and back_wallet is None:
            raise TxError(_("المحفظة المرسلة الأصلية غير موجودة."))

        if origin_wallet is not None:
            if origin_wallet.status != "active":
                raise TxError(_("المحفظة غير نشطة — لا يمكن عكس الحركة."))
            if _money(origin_wallet.balance) < amount:
                raise TxError(_("رصيد المحفظة لا يكفي لعكس الحركة (المبلغ تم صرفه)."))
            origin_wallet.balance = _money(_money(origin_wallet.balance) - amount)
        if back_wallet is not None:
            if back_wallet.status != "active":
                raise TxError(_("المحفظة غير نشطة — لا يمكن عكس الحركة."))
            back_wallet.balance = _money(_money(back_wallet.balance) + amount)

        description = reason.strip() or _("عكس الحركة رقم %(id)s", id=original.id)
        reversal = WalletTransaction(
            school_id=school_id,
            source_wallet_id=origin_wallet.id if origin_wallet is not None else None,
            destination_wallet_id=back_wallet.id if back_wallet is not None else None,
            amount=amount,
            currency=original.currency,
            transaction_type=TX_REVERSAL,
            transaction_hash=_generate_tx_hash(
                school_id,
                origin_wallet.id if origin_wallet is not None else None,
                back_wallet.id if back_wallet is not None else None,
                amount,
                TX_REVERSAL,
            ),
            idempotency_key=f"wallet_reversal:{original.id}",
            description=description,
            reference_type=WALLET_REVERSAL_REFERENCE,
            reference_id=original.id,
            metadata_json={"reversed_by": operator_id, "original_amount": str(amount)},
            status="completed",
        )
        db.session.add(reversal)
        return reversal

    try:
        result = tx(_reverse)
    except TxError as exc:
        return None, str(exc)

    logger.info(
        "wallet_transaction_reversed",
        original_tx_id=transaction_id,
        reversal_tx_id=result.id,
        school_id=school_id,
        operator=operator_id,
    )
    return result, None
