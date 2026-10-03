"""`constants.py` — statics hub.

Single source for reusable magic values/strings/numbers that appear in more than
one module or template. Per-route local literals stay in their routes.

WARNING: msgids / user-facing translatable strings stay in `app/core/labels.py`
and babel catalogs — never paste translatable sentences here.
"""

from __future__ import annotations

# ── Generic UI defaults ──────────────────────────────────────────────────────

DEFAULT_PAGE_SIZE = 20
MIN_PAGE = 1

# ── Attendance notes ──────────────────────────────────────────────────────────

# One note per student per day (Attendance.note). Mirrors the Length(max=1000)
# used by the WTForms note fields (billing/tutoring) so every note field in the
# app shares one budget; enforced server-side because the attendance form posts
# raw request.form (no WTForms validation).
ATTENDANCE_NOTE_MAX_LEN = 1000

AUTODISMIT_FLASH_MS = 5000

# Scroll-reveal defaults (must stay in sync with the small inline <style> the
# templates inject for `.azad-in-view` — see Agent 7 work on residual <style>).
SCROLL_REVEAL_THRESHOLD = 0.1
SCROLL_REVEAL_ROOT_MARGIN = "0px 0px -40px 0px"

# ── Icon sprite ──────────────────────────────────────────────────────────────

ICON_SPRITE_FILENAME = "img/icons.svg"
ICON_HREF_PREFIX = "#i-"

# ── Static, non-translatable UI fragments ───────────────────────────────────

# These are short structural fragments / keys / placeholders, NOT sentences.
# Translatable sentences live in labels.py + babel catalogs.
AI_QUOTA_CACHE_TTL_SEC = 30


# ── Commonly reused message ids (keys only, not translations) ───────────────

# kept as keys for code-readability; actual translations always via _() / labels.
LBL_ROLE = "role"
LBL_SUBSCRIPTION_STATUS = "subscription_status"
LBL_CONTENT_STATUS = "content_status"
LBL_ATTEMPT_STATUS = "attempt_status"
LBL_GRADE_APPEAL_STATUS = "grade_appeal_status"
LBL_TUTORING_REQUEST_STATUS = "tutoring_request_status"
LBL_TUTORING_SESSION_STATUS = "tutoring_session_status"
LBL_TUTORING_PAYMENT_STATUS = "tutoring_payment_status"
LBL_TUTORING_MODE = "tutoring_mode"
