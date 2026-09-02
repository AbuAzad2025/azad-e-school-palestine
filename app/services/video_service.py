"""Video Security & DRM — HLS streaming with dynamic tokens.

P5-01: HMAC SHA-256 stream tokens for time-limited access.
P5-02: Presigned URLs for master/variant playlists.
P5-03: All media served from non-public protected storage.
P5-04: Tenancy-scoped: tokens embed school_id + lesson_id.

Usage:
    token = generate_stream_token(user_id=42, school_id=1, lesson_id=10)
    # Token valid for 15 minutes, HMAC-signed
    verify_stream_token(token, user_id=42, school_id=1, lesson_id=10)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from flask import current_app

from app.core.logging import get_logger

logger = get_logger(__name__)

# Token lifetime in seconds (15 minutes)
_DEFAULT_TOKEN_EXPIRY = 900

# HMAC key derived from SECRET_KEY
_HMAC_KEY_SALT = b"azad-video-stream-v1"


def _get_hmac_key() -> bytes:
    """Derive HMAC key from Flask SECRET_KEY."""
    secret = current_app.config.get("SECRET_KEY", "")
    return hashlib.sha256(secret.encode() + _HMAC_KEY_SALT).digest()


def generate_stream_token(
    user_id: int,
    school_id: int,
    lesson_id: int,
    expires_in: int = _DEFAULT_TOKEN_EXPIRY,
) -> str:
    """Generate an HMAC-signed stream access token.

    Token payload:
        user_id:school_id:lesson_id:expires_at
    Signature:
        HMAC-SHA256 of payload

    Args:
        user_id: Accessing user.
        school_id: Tenant school (for tenancy enforcement).
        lesson_id: Target lesson.
        expires_in: Token lifetime in seconds (default 15 min).

    Returns:
        URL-safe base64 encoded token string.
    """
    expires_at = int(time.time()) + expires_in
    payload = f"{user_id}:{school_id}:{lesson_id}:{expires_at}"
    key = _get_hmac_key()
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    token_data = f"{payload}:{signature}"
    return urlsafe_b64encode(token_data.encode()).decode()


def verify_stream_token(
    token: str,
    user_id: int,
    school_id: int,
    lesson_id: int,
) -> tuple[bool, str | None]:
    """Verify a stream access token.

    Checks:
        1. Token format is valid
        2. HMAC signature matches
        3. Token has not expired
        4. user_id, school_id, lesson_id match

    Args:
        token: The base64-encoded token to verify.
        user_id: Expected user ID.
        school_id: Expected school ID.
        lesson_id: Expected lesson ID.

    Returns:
        (True, None) if valid, (False, error_message) if invalid.
    """
    try:
        token_data = urlsafe_b64decode(token.encode()).decode()
        parts = token_data.split(":")
        if len(parts) != 5:
            return False, "Invalid token format"

        t_user_id_s, t_school_id_s, t_lesson_id_s, t_expires_at_s, t_signature = parts
        tok_user_id = int(t_user_id_s)
        tok_school_id = int(t_school_id_s)
        tok_lesson_id = int(t_lesson_id_s)
        tok_expires_at = int(t_expires_at_s)

        # Verify HMAC signature
        payload = f"{tok_user_id}:{tok_school_id}:{tok_lesson_id}:{tok_expires_at}"
        key = _get_hmac_key()
        expected_sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(t_signature, expected_sig):
            return False, "Invalid token signature"

        # Verify expiry
        if time.time() > tok_expires_at:
            return False, "Token has expired"

        # Verify parameters match
        if tok_user_id != user_id:
            return False, "Token user mismatch"
        if tok_school_id != school_id:
            return False, "Token school mismatch"
        if tok_lesson_id != lesson_id:
            return False, "Token lesson mismatch"

        return True, None

    except (ValueError, TypeError):
        return False, "Invalid token format"


def get_protected_media_path(school_id: int, lesson_id: int) -> str:
    """Get the protected media directory for a lesson.

    Returns path: storage/protected_media/{school_id}/{lesson_id}/
    """
    base = current_app.config.get(
        "PROTECTED_MEDIA_FOLDER",
        os.path.join(
            str(current_app.config.get("UPLOAD_FOLDER", "instance/uploads")),
            "protected_media",
        ),
    )
    return os.path.join(str(base), str(school_id), str(lesson_id))


def get_stream_url(
    user_id: int,
    school_id: int,
    lesson_id: int,
    filename: str,
    expires_in: int = _DEFAULT_TOKEN_EXPIRY,
) -> str:
    """Generate a signed stream URL for a video file.

    URL format:
        /media/stream/{lesson_id}/{filename}?token={hmac_token}&uid={user_id}&sid={school_id}

    Args:
        user_id: Accessing user.
        school_id: Tenant school.
        lesson_id: Target lesson.
        filename: The HLS file (master.m3u8 or segment.ts).
        expires_in: Token lifetime in seconds.

    Returns:
        Signed URL path with query parameters.
    """
    from flask import url_for

    token = generate_stream_token(user_id, school_id, lesson_id, expires_in)
    return (
        url_for("media.stream_video", lesson_id=lesson_id, filename=filename)
        + f"?token={token}&uid={user_id}&sid={school_id}"
    )


def get_master_playlist_url(
    user_id: int,
    school_id: int,
    lesson_id: int,
    expires_in: int = _DEFAULT_TOKEN_EXPIRY,
) -> str:
    """Get the signed URL for the master HLS playlist."""
    return get_stream_url(user_id, school_id, lesson_id, "master.m3u8", expires_in)


def validate_lesson_access(
    user_id: int,
    school_id: int,
    lesson_id: int,
) -> tuple[bool, str | None]:
    """Validate that a user can access a lesson (tenancy + membership).

    Checks:
        1. Lesson exists and belongs to the school
        2. User is a class member, teacher, or school admin

    Args:
        user_id: Accessing user.
        school_id: Expected school.
        lesson_id: Target lesson.

    Returns:
        (True, None) if access allowed, (False, error_message) if denied.
    """
    from app.extensions import db
    from app.models.class_room import ClassMember, ClassRoom
    from app.models.content import Lesson
    from app.models.user import User, UserRole

    lesson = db.session.get(Lesson, lesson_id)
    if not lesson:
        return False, "Lesson not found"

    class_room = db.session.get(ClassRoom, lesson.class_id)
    if not class_room:
        return False, "Class not found"

    if class_room.school_id != school_id:
        return False, "Lesson belongs to a different school"

    user = db.session.get(User, user_id)
    if not user:
        return False, "User not found"

    # super_admin always has access
    if user.role == UserRole.super_admin:
        return True, None

    # School admin of this school has access
    if user.role == UserRole.school_admin:
        from app.core.tenancy import current_school_id

        if current_school_id() == school_id:
            return True, None

    # Teacher of this class has access
    if class_room.teacher_id == user_id:
        return True, None

    # Class member has access
    member = ClassMember.query.filter_by(class_id=class_room.id, user_id=user_id, status="active").first()
    if member:
        return True, None

    return False, "Access denied"
