"""خدمات الدروس الخصوصية — سوق حر خارج عزل المدرسة (استثناء تينانتس §3.15).

الوصول بصلاحية: طرفا الجلسة فقط + super_admin. لا school_id هنا إطلاقاً.
"""

import hashlib
import os
import secrets

from app.core.db import tx
from app.extensions import db
from app.models.tutoring import TutoringRequest, TutoringSession, TutorProfile
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
        return None, "لديك ملف دروس خصوصية مسبقاً."
    code = _invite_code()
    while TutorProfile.query.filter_by(invite_code=code).first():
        code = _invite_code()

    def _create():
        return TutorProfile(
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

    return tx(_create), None


def get_profile(tutor_id: int) -> TutorProfile | None:
    return TutorProfile.query.filter_by(tutor_id=tutor_id).first()


def search_tutors(q: str | None = None, subject: str | None = None):
    query = TutorProfile.query.filter_by(is_active=True)
    if subject:
        query = query.filter(TutorProfile.subject.ilike(f"%{subject}%"))
    if q:
        query = query.filter(db.or_(TutorProfile.subject.ilike(f"%{q}%"), TutorProfile.bio.ilike(f"%{q}%")))
    return query.order_by(TutorProfile.updated_at.desc()).all()


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
        return None, "لديك طلب معلّق لهذا المعلم."

    def _create():
        return TutoringRequest(
            tutor_id=tutor_id,
            student_id=student_id,
            subject=subject,
            preferred_time=preferred_time,
            mode=mode,
            price_quote=price_quote,
            note=note,
        )

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
                    subject=request_.subject or "دروس خصوصية",
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
        return TutoringSession(
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

    return tx(_create)


def update_session(session_: TutoringSession, **fields) -> None:
    def _update():
        for key, value in fields.items():
            if hasattr(session_, key):
                setattr(session_, key, value)

    tx(_update)


def list_requests_for_tutor(tutor_id: int):
    return TutoringRequest.query.filter_by(tutor_id=tutor_id).order_by(TutoringRequest.created_at.desc()).all()


def list_requests_for_student(student_id: int):
    return TutoringRequest.query.filter_by(student_id=student_id).order_by(TutoringRequest.created_at.desc()).all()


def list_sessions_for(user_id: int, as_tutor: bool):
    query = (
        TutoringSession.query.filter_by(tutor_id=user_id)
        if as_tutor
        else TutoringSession.query.filter_by(student_id=user_id)
    )
    return query.order_by(TutoringSession.scheduled_at.desc()).all()


def can_access(user, session_: TutoringSession) -> bool:
    """الوصول لطرفي الجلسة فقط + super_admin (استثناء تينانتس)."""
    if user.role == UserRole.super_admin:
        return True
    return user.id in (session_.tutor_id, session_.student_id)


def generate_live_session_url(session_id: int, user_id: int) -> str | None:
    """
    يولد URL لجلسة مباشرة (Jitsi Meet) لجلسة محددة.
    يُستدعى من المعلم أو الطالب بناءً على الدور.
    """
    session_ = TutoringSession.query.get_or_404(session_id)
    # التحقق من الصلاحية: المعلم أو الطالب في هذه الجلسة
    if session_.tutor_id != user_id and session_.student_id != user_id:
        return None

    # إعدادات Jitsi Meet - قابلة للتكوين عبر متغيرات البيئة
    jitsi_domain = os.getenv("JITSI_DOMAIN", "meet.jit.si")
    # توليد اسم غرفة آمن: بادئة + session_id + hash عشوائي للأمان
    salt = os.getenv("JITSI_ROOM_SALT", "azad-e-school-salt")
    room_hash = hashlib.sha256(f"{session_id}:{user_id}:{salt}".encode()).hexdigest()[:12]
    room_name = f"azad-tutoring-{session_id}-{room_hash}"

    # بناء URL مع معاملات إضافية للتحكم في الغرفة
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
