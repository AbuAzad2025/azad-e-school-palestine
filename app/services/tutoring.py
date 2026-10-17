"""خدمات الدروس الخصوصية — سوق حر خارج عزل المدرسة (استثناء تينانتس §3.15).

الوصول بصلاحية: طرفا الجلسة فقط + super_admin. لا school_id هنا إطلاقاً.
"""

import hashlib
import os
import secrets
from datetime import UTC
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.config.constants import TUTOR_MIN_PAYOUT
from app.core.db import TxError, tx
from app.core.i18n import _
from app.core.logging import get_logger
from app.extensions import db
from app.models.tutoring import (
    TutorCommission,
    TutoringRequest,
    TutoringSession,
    TutorPayout,
    TutorProfile,
    TutorReview,
)
from app.models.user import UserRole

logger = get_logger(__name__)

# أنواع معاملات دفتر المحفظة (P7) المستعملة هنا — تصدير لأغراض الاختبار.
# الدفع الوارد من الطالب خارج المنصة يمثّل تدفقًا خارجيًا داخل النظام.
TX_INFLOW_TYPE = "tutor_session_credit"
TX_TUTOR_COMMISSION = "tutor_commission"  # نوع P7 — يحاكي الثابت في wallet_service


def _invite_code() -> str:
    return secrets.token_urlsafe(8)


def create_tutor_profile(
    tutor_id: int,
    subject: str,
    price_hour=None,
    price_session=None,
    mode: str = "both",
    grade_levels: list | None = None,
    availability: dict | None = None,
    bio: str | None = None,
) -> tuple[TutorProfile | None, str | None]:
    """ينشئ ملف معلم خصوصي (ملف واحد لكل معلم)."""
    if TutorProfile.query.filter_by(tutor_id=tutor_id).first():
        return None, _("لديك ملف دروس خصوصية مسبقاً.")
    code = _invite_code()
    while TutorProfile.query.filter_by(invite_code=code).first():
        code = _invite_code()

    def _create():
        p = TutorProfile(
            tutor_id=tutor_id,
            subject=subject.strip(),
            price_hour=price_hour,
            price_session=price_session,
            mode=mode,
            grade_levels=grade_levels,
            availability=availability,
            bio=bio,
            invite_code=code,
        )
        db.session.add(p)
        return p

    return tx(_create), None


def get_profile(tutor_id: int) -> TutorProfile | None:
    return TutorProfile.query.filter_by(tutor_id=tutor_id).first()


def search_tutors(q: str | None = None, subject: str | None = None):
    query = TutorProfile.query.filter_by(is_active=True)
    if subject:
        query = query.filter(TutorProfile.subject.ilike(f"%{subject}%"))
    if q:
        query = query.filter(db.or_(TutorProfile.subject.ilike(f"%{q}%"), TutorProfile.bio.ilike(f"%{q}%")))
    return query.options(joinedload(TutorProfile.tutor)).order_by(TutorProfile.updated_at.desc()).all()


def find_by_invite_code(code: str) -> TutorProfile | None:
    return TutorProfile.query.filter_by(invite_code=code.strip()).first()


def update_profile(profile: TutorProfile, **fields) -> None:
    def _update():
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

    tx(_update)


def create_request(
    tutor_id: int,
    student_id: int,
    subject: str,
    preferred_time,
    mode: str = "online",
    price_quote=None,
    note: str | None = None,
) -> tuple[TutoringRequest | None, str | None]:
    """طلب حجز من طالب لمعلم. يمنع طلباً مفتوحاً مكرراً."""
    open_req = TutoringRequest.query.filter_by(tutor_id=tutor_id, student_id=student_id, status="pending").first()
    if open_req:
        return None, _("لديك طلب معلّق لهذا المعلم.")

    def _create():
        req = TutoringRequest(
            tutor_id=tutor_id,
            student_id=student_id,
            subject=subject,
            preferred_time=preferred_time,
            mode=mode,
            price_quote=price_quote,
            note=note,
        )
        db.session.add(req)
        return req

    return tx(_create), None


def respond_request(request_: TutoringRequest, accept: bool) -> None:
    """المعلم يقبل/يرفض الطلب. القبول يولّد جلسة أولية."""

    def _respond():
        request_.status = "accepted" if accept else "rejected"
        if accept:
            db.session.add(
                TutoringSession(
                    request_id=request_.id,
                    tutor_id=request_.tutor_id,
                    student_id=request_.student_id,
                    subject=request_.subject or _("دروس خصوصية"),
                    scheduled_at=request_.preferred_time,
                    mode=request_.mode,
                    price=request_.price_quote,
                    status="requested",
                )
            )

    tx(_respond)


def create_session(
    tutor_id: int,
    student_id: int,
    subject: str,
    scheduled_at,
    mode: str = "online",
    duration_min: int | None = None,
    price=None,
    online_link: str | None = None,
    location: str | None = None,
    request_id: int | None = None,
) -> TutoringSession:
    def _create():
        s = TutoringSession(
            request_id=request_id,
            tutor_id=tutor_id,
            student_id=student_id,
            subject=subject,
            scheduled_at=scheduled_at,
            mode=mode,
            duration_min=duration_min,
            price=price,
            online_link=online_link,
            location=location,
        )
        db.session.add(s)
        return s

    return tx(_create)


def update_session(session_: TutoringSession, **fields) -> None:
    def _update():
        for key, value in fields.items():
            if hasattr(session_, key):
                setattr(session_, key, value)

    tx(_update)


def list_requests_for_tutor(tutor_id: int):
    return (
        TutoringRequest.query.filter_by(tutor_id=tutor_id)
        .options(joinedload(TutoringRequest.student))
        .order_by(TutoringRequest.created_at.desc())
        .all()
    )


def list_requests_for_student(student_id: int):
    return (
        TutoringRequest.query.filter_by(student_id=student_id)
        .options(joinedload(TutoringRequest.tutor))
        .order_by(TutoringRequest.created_at.desc())
        .all()
    )


def list_sessions_for(user_id: int, as_tutor: bool):
    query = (
        TutoringSession.query.filter_by(tutor_id=user_id)
        if as_tutor
        else TutoringSession.query.filter_by(student_id=user_id)
    )
    if as_tutor:
        query = query.options(joinedload(TutoringSession.student))
    else:
        query = query.options(joinedload(TutoringSession.tutor))
    return query.order_by(TutoringSession.scheduled_at.desc()).all()


def can_access(user, session_: TutoringSession) -> bool:
    """الوصول لطرفي الجلسة فقط + super_admin (استثناء تينانتس)."""
    if user.role == UserRole.super_admin:
        return True
    return user.id in (session_.tutor_id, session_.student_id)


def generate_zoom_meeting(session_id: int, user_id: int) -> tuple[str | None, str | None]:
    import base64
    import json
    import os
    import urllib.error
    import urllib.request

    session_ = db.session.get(TutoringSession, session_id)
    if not session_:
        return None, _("الجلسة غير موجودة.")
    if session_.tutor_id != user_id and session_.student_id != user_id:
        return None, _("غير مصرح.")

    account_id = os.getenv("ZOOM_ACCOUNT_ID", "")
    client_id = os.getenv("ZOOM_CLIENT_ID", "")
    client_secret = os.getenv("ZOOM_CLIENT_SECRET", "")

    if not all([account_id, client_id, client_secret]):
        return None, _("إعدادات Zoom غير مكتملة.")

    token_url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
    token_data = f"{client_id}:{client_secret}".encode()
    token_auth = base64.b64encode(token_data).decode()

    try:
        req = urllib.request.Request(token_url, method="POST")
        req.add_header("Authorization", f"Basic {token_auth}")
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — Zoom OAuth endpoint over HTTPS
            token_resp = json.loads(resp.read())
        access_token = token_resp["access_token"]
    except Exception as e:
        return None, _("فشل الحصول على رمز Zoom: %(detail)s", detail=e)

    start_time = session_.scheduled_at.isoformat() if session_.scheduled_at else None
    duration = session_.duration_min or 60
    topic = f"أزاد - {session_.subject} - جلسة #{session_id}"

    meeting_payload = {
        "topic": topic,
        "type": 2,
        "start_time": start_time,
        "duration": duration,
        "timezone": "Asia/Jerusalem",
        "settings": {
            "waiting_room": True,
            "host_video": True,
            "participant_video": True,
            "join_before_host": False,
        },
    }

    try:
        req = urllib.request.Request(
            "https://api.zoom.us/v2/users/me/meetings",
            data=json.dumps(meeting_payload).encode(),
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 — Zoom API endpoint over HTTPS
            meeting_resp = json.loads(resp.read())

        zoom_meeting_id = str(meeting_resp.get("id", ""))
        zoom_join_url = meeting_resp.get("join_url", "")
        zoom_start_url = meeting_resp.get("start_url", "")

        def _update():
            session_.zoom_meeting_id = zoom_meeting_id
            session_.zoom_join_url = zoom_join_url
            session_.zoom_start_url = zoom_start_url
            session_.video_provider = "zoom"

        tx(_update)

        return zoom_join_url, None
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        return None, f"Zoom API error: {e.code} — {body}"
    except Exception as e:
        return None, _("خطأ غير متوقع: %(detail)s", detail=e)


def generate_live_session_url(session_id: int, user_id: int) -> str | None:
    session_ = db.get_or_404(TutoringSession, session_id)
    if session_.tutor_id != user_id and session_.student_id != user_id:
        return None

    provider = getattr(session_, "video_provider", "jitsi") or "jitsi"

    if provider == "zoom":
        if session_.zoom_join_url:
            return session_.zoom_join_url
        join_url, error = generate_zoom_meeting(session_id, user_id)
        if join_url:
            return join_url
        return None

    jitsi_domain = os.getenv("JITSI_DOMAIN", "meet.jit.si")
    salt = os.getenv("JITSI_ROOM_SALT", "azad-e-school-salt")
    room_hash = hashlib.sha256(f"{session_id}:{user_id}:{salt}".encode()).hexdigest()[:12]
    room_name = f"azad-tutoring-{session_id}-{room_hash}"
    params = {
        "userInfo.displayName": f"User-{user_id}",
        "config.prejoinPageEnabled": "false",
        "config.startWithAudioMuted": "true",
        "config.startWithVideoMuted": "true",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://{jitsi_domain}/{room_name}?{query_string}"


def update_session_live_status(
    session_: TutoringSession, live_status: str = "active", online_link: str | None = None, user_id: int | None = None
) -> str | None:
    """
    يحديث حالة الجلسة الحية و الرابط.
    يمكن للمعلم تحديثها عند بدء الجلسة.
    يعيد الرابط المولد إذا كان جديداً.
    """

    def _update():
        if live_status:
            session_.status = live_status
        if online_link:
            session_.online_link = online_link
        elif live_status == "active" and user_id:
            # توليد رابط تلقائياً عند بدء الجلسة
            generated = generate_live_session_url(session_.id, user_id)
            if generated:
                session_.online_link = generated
                return generated
        return None

    return tx(_update)


def get_active_sessions_for_student(student_id: int) -> list[TutoringSession]:
    """يحصل على الجلسات النشطة للطالب."""
    return (
        TutoringSession.query.filter_by(student_id=student_id, status="active")
        .options(joinedload(TutoringSession.tutor))
        .order_by(TutoringSession.scheduled_at.desc())
        .all()
    )


def get_active_sessions_for_tutor(tutor_id: int) -> list[TutoringSession]:
    """يحصل على الجلسات النشطة للمعلم."""
    return (
        TutoringSession.query.filter_by(tutor_id=tutor_id, status="active")
        .options(joinedload(TutoringSession.student))
        .order_by(TutoringSession.scheduled_at.desc())
        .all()
    )


def rate_session(
    session_id: int, student_id: int, rating: int, comment: str | None = None
) -> tuple[TutorReview | None, str | None]:
    """تقييم جلسة خصوصية."""
    from datetime import datetime, timedelta

    from app.extensions import db

    session_ = db.session.get(TutoringSession, session_id)
    if not session_:
        return None, _("الجلسة غير موجودة.")
    if session_.student_id != student_id:
        return None, _("ليس لديك صلاحية تقييم هذه الجلسة.")
    if session_.status not in ("completed", "ended"):
        return None, _("لا يمكن تقييم جلسة لم تنتهِ بعد.")

    end_time = session_.end_time or session_.scheduled_at
    if session_.duration_min and session_.scheduled_at:
        end_time = session_.scheduled_at + timedelta(minutes=session_.duration_min)

    if end_time:
        now = datetime.now(UTC)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=UTC)
        if now - end_time > timedelta(hours=24):
            return None, _("انتهى وقت التقييم (24 ساعة بعد انتهاء الجلسة).")

    existing = db.session.execute(
        db.select(TutorReview).where(TutorReview.session_id == session_id, TutorReview.student_id == student_id)
    ).scalar_one_or_none()
    if existing:
        return None, _("لقد قيّمت هذه الجلسة مسبقاً.")

    if not (1 <= rating <= 5):
        return None, _("التقييم يجب أن يكون بين 1 و 5.")

    def _rate():
        review = TutorReview(
            session_id=session_id,
            student_id=student_id,
            rating=rating,
            comment=(comment or "").strip() or None,
        )
        db.session.add(review)
        return review

    return tx(_rate), None


COMMISSION_RATE = 20.0  # 20% platform fee


def get_tutor_earnings(tutor_id: int) -> dict:
    """ملخص أرباح المعلم (batch — استخدام SQL aggregation بدلاً من تحميل كامل)."""
    # Aggregate sessions in one query
    session_agg = (
        db.session.query(
            func.count(TutoringSession.id).label("total_sessions"),
            func.sum(
                func.cast(
                    db.case(
                        (TutoringSession.status.in_(["completed", "ended"]), TutoringSession.price),
                        else_=0,
                    ),
                    db.Numeric,
                )
            ).label("total_earnings"),
            func.sum(
                func.cast(
                    db.case(
                        (
                            db.and_(
                                TutoringSession.payment_status == "pending",
                                TutoringSession.status.notin_(["cancelled"]),
                            ),
                            TutoringSession.price,
                        ),
                        else_=0,
                    ),
                    db.Numeric,
                )
            ).label("pending_payouts"),
            func.count(
                db.case(
                    (TutoringSession.status.in_(["completed", "ended"]), 1),
                    else_=None,
                )
            ).label("completed_sessions"),
        )
        .filter(TutoringSession.tutor_id == tutor_id)
        .one()
    )

    total_earnings = float(session_agg.total_earnings or 0)
    pending = float(session_agg.pending_payouts or 0)
    completed_count = session_agg.completed_sessions or 0
    total_sessions = session_agg.total_sessions or 0

    # Aggregate reviews in one query
    review_agg = (
        db.session.query(
            func.avg(TutorReview.rating).label("avg_rating"),
            func.count(TutorReview.id).label("review_count"),
        )
        .join(TutoringSession)
        .filter(TutoringSession.tutor_id == tutor_id)
        .one()
    )

    avg_rating = round(float(review_agg.avg_rating or 0), 1)
    review_count = review_agg.review_count or 0

    # Commission calculations
    commission_amount = round(total_earnings * COMMISSION_RATE / 100, 2)
    net_earnings = round(total_earnings - commission_amount, 2)

    # Withdrawable — batch aggregation
    withdrawable = float(
        db.session.query(func.sum(TutorCommission.tutor_net))
        .filter(TutorCommission.tutor_id == tutor_id, TutorCommission.status == "pending")
        .scalar()
        or 0
    )

    total_payouts = float(
        db.session.query(func.sum(TutorPayout.amount))
        .filter(TutorPayout.tutor_id == tutor_id, TutorPayout.status == "approved")
        .scalar()
        or 0
    )

    # AZ-P0-04: شفافية الرصيد — عدّاد العمولات المعلّقة، ومطابقة "المتاح للسحب"
    # لمكوّنات سجل العمولة نفسه (session_amount − commission_amount) لا لمجموع
    # مطابق. أي انحراف بين العمود المخزَّن ومكوّناته يظهر تنبيهاً في الواجهة
    # بدل رقم صامت يوحي بأن الرصيد سليم.
    commission_agg = (
        db.session.query(
            func.count(TutorCommission.id).label("pending_count"),
            func.sum(TutorCommission.session_amount - TutorCommission.commission_amount).label("expected_net"),
        )
        .filter(TutorCommission.tutor_id == tutor_id, TutorCommission.status == "pending")
        .one()
    )
    pending_commission_count = commission_agg.pending_count or 0
    ledger_net = round(float(commission_agg.expected_net or 0), 2)
    withdrawable_r = round(withdrawable, 2)

    return {
        "total_earnings": round(total_earnings, 2),
        "pending_payouts": round(pending, 2),
        "avg_rating": avg_rating,
        "review_count": review_count,
        "completed_sessions": completed_count,
        "total_sessions": total_sessions,
        "commission_amount": commission_amount,
        "net_earnings": net_earnings,
        "withdrawable": withdrawable_r,
        "total_payouts": round(float(total_payouts), 2),
        "commission_rate": COMMISSION_RATE,
        "pending_commission_count": pending_commission_count,
        "ledger_net": ledger_net,
        "balance_consistent": abs(withdrawable_r - ledger_net) < 0.01,
        "minimum_payout": TUTOR_MIN_PAYOUT,
        "shortfall": max(0.0, round(TUTOR_MIN_PAYOUT - withdrawable_r, 2)),
        "can_request_payout": withdrawable_r >= TUTOR_MIN_PAYOUT,
    }


def create_commission_record(session: TutoringSession) -> TutorCommission | None:
    """ينشئ سجل عمولة عند اكتمال الجلسة — **مع إدخال دفتر المحفظة** (P7).

    P0-10: FOR UPDATE + فحص مزدوج لمنع إنشاء عمولة مكررة تحت التزامن.

    التكامل (سدًّا للفجوة الجدولية المعزولة): إضافة لوصول وجود سجل --
    كل عملية إنشاء عمولة تؤدي الآن إلى إدخال دفتر واقعي في المحفظة
    (معاملة زيادة ``tutor_commission``): شبكة قيمة الأساس إلى شبكة
    المحفظة للحساب (مزيل مزدوج: خادم حقيقي لا رصيد). إدخال الدفتر
    استثناء مقصود (فجورة أو مال لا يكفي): سجل العمولة نفسه دائمًا
    يُنشأ — لا تنهار نهاية الجلسة لسؤال: محفظة غير موجودة.
    """
    if session.status not in ("completed", "ended"):
        return None

    def _create():
        # FOR UPDATE على الجلسة لمنع المعالجة المتزامنة
        locked = db.session.execute(
            db.select(TutoringSession).where(TutoringSession.id == session.id).with_for_update()
        ).scalar_one_or_none()
        if not locked or locked.status not in ("completed", "ended"):
            return None
        existing = TutorCommission.query.filter_by(session_id=locked.id).first()
        if existing:
            return None

        amount = float(locked.price or 0)
        commission = round(amount * COMMISSION_RATE / 100, 2)
        net = round(amount - commission, 2)

        c = TutorCommission(
            session_id=locked.id,
            tutor_id=locked.tutor_id,
            session_amount=amount,
            commission_rate=COMMISSION_RATE,
            commission_amount=commission,
            tutor_net=net,
        )
        db.session.add(c)
        _append_commission_ledger(locked, amount_dec=Decimal(str(amount)), commission_dec=Decimal(str(commission)))
        return c

    return tx(_create)


def _append_commission_ledger(locked: TutoringSession, *, amount_dec: Decimal, commission_dec: Decimal) -> None:
    """سجّل الدفعة في دفتر المحفظة (أنواع P7 ``tutor_commission``) — داخل tx() الحالي.

    القيد المزدوج لجلسة مكتملة، كساقين:
        1. تكوين صافي: تدفق خارجي إلى محفظة المعلم (source NULL) — قيمة
           الجلسة داخلت المنصة من الطالب (يُدفع خارجيًا).
        2. عمولة المنصة: سحب عمولة من حساب المعلم إلى خارج النظام
           (destination NULL) — النوع P7 ``tutor_commission`` تحديدًا.
    مجموع الأثر الصافي: صافي المعلم المحفوظ في سجل العمولة — بلا
    حساب "منصة" مخترع: القيود للخارج ممثلة بجانب NULL (نفس الممثّل الذي
    يستخدمه ``admin_credit`` للإيداع الإداري).

    الفشل ليس فادحًا: سجل العمولة سبق أن أُنشئ (والجلسة مكتملة). النقص
    يُسجّل لا يُرفع — إنهاء جلسة لا يجب أن ينهار لأن المحفظة غير موجودة.
    """
    from app.models.wallet import Wallet, WalletTransaction
    from app.services.wallet_service import _generate_tx_hash, _money

    school_id = getattr(locked.tutor, "school_id", None)
    if not school_id:
        logger.info(
            "commission_ledger_skipped_no_school",
            session_id=locked.id,
            tutor_id=locked.tutor_id,
        )
        return

    wallet = db.session.query(Wallet).filter_by(school_id=school_id, user_id=locked.tutor_id).with_for_update().first()
    if wallet is None:
        logger.info("commission_ledger_skipped_no_wallet", session_id=locked.id, tutor_id=locked.tutor_id)
        return

    _money(amount_dec - commission_dec)  # صافي المعلم محفوظ في سجل العمولة — غير مستخدم هنا
    commission_dec = _money(commission_dec)
    amount_dec = _money(amount_dec)
    base_key = f"tutoring_session:{locked.id}"  # مفاتيح مستقرة — إعادة الاستدعاء لا تكرر

    # 1) التدفق الخارجي الداخل إلى محفظة المعلم (source NULL)
    inflow_exists = WalletTransaction.query.filter_by(idempotency_key=f"{base_key}:inflow").first()
    if not inflow_exists:
        db.session.add(
            WalletTransaction(
                school_id=school_id,
                source_wallet_id=None,
                destination_wallet_id=wallet.id,
                amount=amount_dec,
                currency=wallet.currency,
                transaction_type=TX_INFLOW_TYPE,
                transaction_hash=_generate_tx_hash(school_id, None, wallet.id, amount_dec, TX_INFLOW_TYPE),
                idempotency_key=f"{base_key}:inflow",
                description=f"جلسة خصوصية #{locked.id} — قبض المعلم",
                reference_type="tutoring_session",
                reference_id=locked.id,
                status="completed",
            )
        )
        wallet.balance = _money(wallet.balance + amount_dec)

    # 2) عمولة المنصة (نوع P7 tutor_commission) — سحب إلى الخارج
    commission_exists = WalletTransaction.query.filter_by(idempotency_key=f"{base_key}:commission").first()
    if not commission_exists:
        db.session.add(
            WalletTransaction(
                school_id=school_id,
                source_wallet_id=wallet.id,
                destination_wallet_id=None,
                amount=commission_dec,
                currency=wallet.currency,
                transaction_type=TX_TUTOR_COMMISSION,
                transaction_hash=_generate_tx_hash(school_id, wallet.id, None, commission_dec, TX_TUTOR_COMMISSION),
                idempotency_key=f"{base_key}:commission",
                description=f"عمولة المنصة ({COMMISSION_RATE}%) على جلسة #{locked.id}",
                reference_type="tutoring_session",
                reference_id=locked.id,
                status="completed",
            )
        )
        wallet.balance = _money(wallet.balance - commission_dec)


def request_payout(tutor_id: int, amount: float) -> tuple[TutorPayout | None, str | None]:
    """طلب سحب أرباح — الحد الأدنى 200₪.

    P0-10: FOR UPDATE على العمولات المعلّقة لمنع سحب مزدوج تحت التزامن.
    """
    # AZ-P0-04: الحد الأدنى من مصدر واحد — نفس الرقم يحرسه النموذج وتُبنى
    # عليه رسالة القالب، فلا يتباعد قيد الخدمة عن الواجهة.
    if amount < TUTOR_MIN_PAYOUT:
        return None, _("الحد الأدنى للسحب 200₪.")

    def _create():
        # FOR UPDATE على العمولات المعلّقة لمنع السحب المتزامن
        pending = TutorCommission.query.filter_by(tutor_id=tutor_id, status="pending").with_for_update().all()
        withdrawable = sum(float(c.tutor_net) for c in pending)
        if amount > withdrawable:
            raise TxError(
                _(
                    "المبلغ المطلوب (%(amount)s) يتجاوز الرصيد المتاح (%(balance)s).",
                    amount=amount,
                    balance=withdrawable,
                )
            )
        p = TutorPayout(tutor_id=tutor_id, amount=amount)
        db.session.add(p)
        return p

    try:
        return tx(_create), None
    except TxError as exc:
        return None, str(exc)


# ─────────────────────────────────────────────────────────────────────────────
# AZ-P2-13 — دفع آمن للجلسات الخصوصية (تأكيد مزدوج + قيد دفتر واحد)
# ─────────────────────────────────────────────────────────────────────────────


def _finalize_session_payment(locked: TutoringSession) -> None:
    """أقفل الدفعة (داخل tx() الحالي بعد قفل الصف): قيد دفتر واحد idempotent.

    القيد يستعمل مفتاح ``tutoring_session:{id}:inflow`` — نفس المفتاح
    الذي يحرسه ``_append_commission_ledger``
    عند اكتمال الجلسة، فإتمام الدفع ثم اكتمال الجلسة (والعكس) لا يكرّر
    التدفق أبداً، ومحفظة غائبة تُخطى بأمان مع سجل تحذيري أوضح.
    """
    from app.models.wallet import Wallet, WalletTransaction
    from app.services.wallet_service import _generate_tx_hash, _money

    school_id = getattr(locked.tutor, "school_id", None)
    price = locked.price
    if school_id and price:
        wallet = (
            db.session.query(Wallet).filter_by(school_id=school_id, user_id=locked.tutor_id).with_for_update().first()
        )
        if wallet is None:
            logger.info("payment_ledger_skipped_no_wallet", session_id=locked.id, tutor_id=locked.tutor_id)
        else:
            amount_dec = _money(price)
            key = f"tutoring_session:{locked.id}:inflow"
            exists = WalletTransaction.query.filter_by(idempotency_key=key).first()
            if exists is None:
                db.session.add(
                    WalletTransaction(
                        school_id=school_id,
                        source_wallet_id=None,
                        destination_wallet_id=wallet.id,
                        amount=amount_dec,
                        currency=wallet.currency,
                        transaction_type=TX_INFLOW_TYPE,
                        transaction_hash=_generate_tx_hash(school_id, None, wallet.id, amount_dec, TX_INFLOW_TYPE),
                        idempotency_key=key,
                        description=f"جلسة خصوصية #{locked.id} — دفع مؤكد من الطرفين",
                        reference_type="tutoring_session",
                        reference_id=locked.id,
                        status="completed",
                    )
                )
                wallet.balance = _money(wallet.balance + amount_dec)

    locked.payment_status = "paid"
    locked.payment_confirmed_at = locked.updated_at


def confirm_session_payment_by_student(session_id: int, actor_id: int) -> tuple[str | None, str | None]:
    """تأكيد الطالب: أُدفع للمعلم. الإقفال لا يحدث إلا بتأكيد الطرفين معاً.

    يعيد ``"paid"`` عند الإقفال، ``"waiting"`` بانتظار المعلم، و
    ``(None, رسالة)`` في خطأ الصلاحية/التحقق.
    """

    def _work() -> str:
        locked = db.session.execute(
            db.select(TutoringSession).where(TutoringSession.id == session_id).with_for_update()
        ).scalar_one_or_none()
        if locked is None:
            raise TxError(_("الجلسة غير موجودة."))
        if locked.student_id != actor_id:
            raise TxError(_("هذا التأكيد حق الطالب وحده."))
        if locked.payment_status == "paid":
            return "paid"  # بلا تقفل مكرر — لا رسالة خطأ
        locked.student_confirmed_payment = True
        if not locked.tutor_confirmed_payment:
            return "waiting"
        _finalize_session_payment(locked)
        return "paid"

    try:
        return tx(_work), None
    except TxError as exc:
        return None, str(exc)


def confirm_session_payment_by_tutor(session_id: int, actor_id: int) -> tuple[str | None, str | None]:
    """تأكيد المعلم: أستلمت المبلغ. نفس منطق الإقفال المزدوج مع العكس.

    يعيد ``"paid"`` عند الإقفال، أو ``"waiting"`` بانتظار تأكيد الطالب.
    """

    def _work() -> str:
        locked = db.session.execute(
            db.select(TutoringSession).where(TutoringSession.id == session_id).with_for_update()
        ).scalar_one_or_none()
        if locked is None:
            raise TxError(_("الجلسة غير موجودة."))
        if locked.tutor_id != actor_id:
            raise TxError(_("هذا التأكيد حق المعلم وحده."))
        if locked.payment_status == "paid":
            return "paid"
        locked.tutor_confirmed_payment = True
        if not locked.student_confirmed_payment:
            return "waiting"
        _finalize_session_payment(locked)
        return "paid"

    try:
        return tx(_work), None
    except TxError as exc:
        return None, str(exc)


def reject_session_payment_by_tutor(session_id: int, actor_id: int) -> tuple[str | None, str | None]:
    """رفض المعلم: يعيد الجلسة حالة غير مدفوعة وتُمحي التأكيدات.

    الرفض ممنوع بعد إغلاق المال (``paid``) — يُرفض مع رسالة، وتبقى حالة الجلسة كما هي.
    """

    def _work() -> str:
        locked = db.session.execute(
            db.select(TutoringSession).where(TutoringSession.id == session_id).with_for_update()
        ).scalar_one_or_none()
        if locked is None:
            raise TxError(_("الجلسة غير موجودة."))
        if locked.tutor_id != actor_id:
            raise TxError(_("هذا الرفض حق المعلم وحده."))
        if locked.payment_status == "paid":
            raise TxError(_("لا يمكن رفض دفعة مقفلة مسبقاً — الجلسة مدفوعة."))
        locked.student_confirmed_payment = False
        locked.tutor_confirmed_payment = False
        locked.payment_confirmed_at = None
        return "pending"

    try:
        return tx(_work), None
    except TxError as exc:
        return None, str(exc)
