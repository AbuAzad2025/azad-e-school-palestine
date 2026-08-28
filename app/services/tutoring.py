"""خدمات الدروس الخصوصية — سوق حر خارج عزل المدرسة (استثناء تينانتس §3.15).

الوصول بصلاحية: طرفا الجلسة فقط + super_admin. لا school_id هنا إطلاقاً.
"""

import hashlib
import os
import secrets
from datetime import UTC

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.core.db import tx
from app.core.i18n import _
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
    session_ = TutoringSession.query.get_or_404(session_id)
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
        .order_by(TutoringSession.scheduled_at.desc())
        .all()
    )


def get_active_sessions_for_tutor(tutor_id: int) -> list[TutoringSession]:
    """يحصل على الجلسات النشطة للمعلم."""
    return (
        TutoringSession.query.filter_by(tutor_id=tutor_id, status="active")
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
    """ملخص أرباح المعلم."""
    sessions = (
        db.session.execute(db.select(TutoringSession).where(TutoringSession.tutor_id == tutor_id)).scalars().all()
    )
    completed = [s for s in sessions if s.status in ("completed", "ended")]
    total_earnings = sum(float(s.price or 0) for s in completed)
    pending = sum(
        float(s.price or 0) for s in sessions if s.payment_status == "pending" and s.status not in ("cancelled",)
    )

    reviews = (
        db.session.execute(db.select(TutorReview).join(TutoringSession).where(TutoringSession.tutor_id == tutor_id))
        .scalars()
        .all()
    )
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 0.0

    # Commission calculations
    commission_amount = round(total_earnings * COMMISSION_RATE / 100, 2)
    net_earnings = round(total_earnings - commission_amount, 2)

    # Withdrawable (from TutorCommission where status == "pending")
    pending_commissions = TutorCommission.query.filter_by(tutor_id=tutor_id, status="pending").all()
    withdrawable = sum(float(c.tutor_net) for c in pending_commissions)

    total_payouts = (
        db.session.query(func.sum(TutorPayout.amount))
        .filter(TutorPayout.tutor_id == tutor_id, TutorPayout.status == "approved")
        .scalar()
        or 0
    )

    return {
        "total_earnings": round(total_earnings, 2),
        "pending_payouts": round(pending, 2),
        "avg_rating": avg_rating,
        "review_count": len(reviews),
        "completed_sessions": len(completed),
        "total_sessions": len(sessions),
        "commission_amount": commission_amount,
        "net_earnings": net_earnings,
        "withdrawable": round(withdrawable, 2),
        "total_payouts": round(float(total_payouts), 2),
        "commission_rate": COMMISSION_RATE,
    }


def create_commission_record(session: TutoringSession) -> TutorCommission | None:
    """ينشئ سجل عمولة عند اكتمال الجلسة."""
    if session.status not in ("completed", "ended"):
        return None
    existing = TutorCommission.query.filter_by(session_id=session.id).first()
    if existing:
        return None

    amount = float(session.price or 0)
    commission = round(amount * COMMISSION_RATE / 100, 2)
    net = round(amount - commission, 2)

    def _create():
        c = TutorCommission(
            session_id=session.id,
            tutor_id=session.tutor_id,
            session_amount=amount,
            commission_rate=COMMISSION_RATE,
            commission_amount=commission,
            tutor_net=net,
        )
        db.session.add(c)
        return c

    return tx(_create)


def request_payout(tutor_id: int, amount: float) -> tuple[TutorPayout | None, str | None]:
    """طلب سحب أرباح — الحد الأدنى 200₪."""
    if amount < 200:
        return None, _("الحد الأدنى للسحب 200₪.")
    # Check withdrawable balance
    pending = TutorCommission.query.filter_by(tutor_id=tutor_id, status="pending").all()
    withdrawable = sum(float(c.tutor_net) for c in pending)
    if amount > withdrawable:
        return None, _(
            "المبلغ المطلوب (%(amount)s) يتجاوز الرصيد المتاح (%(balance)s).",
            amount=amount,
            balance=withdrawable,
        )

    def _create():
        p = TutorPayout(tutor_id=tutor_id, amount=amount)
        db.session.add(p)
        return p

    return tx(_create), None
