"""Media streaming routes — serve HLS content with token verification.

P5-09: Every stream request verified via HMAC token.
P5-10: Media served from non-public protected_media directory.
P5-11: Tenancy enforced: token must match school_id + lesson_id.
"""

from __future__ import annotations

import os

from app.core.logging import get_logger
from app.services.video_service import (
    get_protected_media_path,
    validate_lesson_access,
    verify_stream_token,
)
from flask import Response, abort, request, send_file
from flask_login import login_required

from . import bp

logger = get_logger(__name__)


@bp.route("/stream/<int:lesson_id>/<path:filename>")
@login_required
def stream_video(lesson_id: int, filename: str) -> Response:
    """Serve HLS video content with token verification.

    URL: /media/stream/{lesson_id}/{filename}?token={hmac}&uid={user_id}&sid={school_id}

    Serves:
        - .m3u8 playlists (master and variant)
        - .ts encrypted video segments
        - encryption.key (for HLS.js player)

    Security:
        - HMAC token verified on every request
        - Token must match user_id, school_id, lesson_id
        - Token expires after 15 minutes (configurable)
        - File access validated against tenancy and class membership
    """
    from flask_login import current_user

    # Extract token parameters
    token = request.args.get("token", "")
    try:
        uid = int(request.args.get("uid", "0"))
        sid = int(request.args.get("sid", "0"))
    except (ValueError, TypeError):
        abort(400)

    # Verify HMAC token
    valid, error = verify_stream_token(token, uid, sid, lesson_id)
    if not valid:
        logger.warning(
            "stream_token_invalid",
            lesson_id=lesson_id,
            filename=filename,
            error=error,
            user_id=uid,
        )
        abort(403)

    # Verify user identity matches token
    if current_user.id != uid:
        abort(403)

    # Validate lesson access (tenancy + membership)
    allowed, access_error = validate_lesson_access(uid, sid, lesson_id)
    if not allowed:
        logger.warning(
            "stream_access_denied",
            lesson_id=lesson_id,
            user_id=uid,
            school_id=sid,
            error=access_error,
        )
        abort(403)

    # Validate filename (prevent path traversal)
    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400)

    # Only allow safe file extensions
    allowed_extensions = {".m3u8", ".ts", ".key"}
    file_ext = os.path.splitext(filename)[1].lower()
    if file_ext not in allowed_extensions:
        abort(400)

    # Build file path
    media_dir = get_protected_media_path(sid, lesson_id)
    file_path = os.path.join(media_dir, filename)

    # Security: verify resolved path is within media_dir
    real_media = os.path.realpath(media_dir)
    real_file = os.path.realpath(file_path)
    if not real_file.startswith(real_media):
        abort(403)

    # Check file exists
    if not os.path.exists(file_path):
        abort(404)

    # Set appropriate content type
    content_types = {
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
        ".key": "application/octet-stream",
    }
    content_type = content_types.get(file_ext, "application/octet-stream")

    logger.info(
        "stream_served",
        lesson_id=lesson_id,
        filename=filename,
        user_id=uid,
        school_id=sid,
    )

    response = send_file(file_path, mimetype=content_type)
    # Prevent caching of encrypted content
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
