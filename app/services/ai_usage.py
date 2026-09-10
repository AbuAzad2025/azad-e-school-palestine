"""استهلاك AI لكل مدرسة — تجميع شهري من ai_usage_logs.

P4-AI-01: فرض حصص tenant_quotas.max_ai_tokens_monthly يتطلب معرفة
استهلاك الشهر الحالي لكل مدرسة. السجلات بلا school_id، لذا نربط عبر
users.school_id (أول دور فعّال). التجميع مخزّن مؤقتاً 60 ثانية.

ملاحظة معمارية: المستخدم الفردي (بلا مدرسة) لا ينتمي لأي تينانت،
ومعالجته تحدث في tenant_ai_quota (core/permissions.py).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models.ai import AiUsageLog
from app.models.user import UserRole, UserRoleLink


def monthly_tokens_used(school_id: int) -> int:
    """إجمالي توكنات AI التي استهلكتها مستخدمو المدرسة في الشهر الحالي.

    الربط: ai_usage_logs.user_id → users.id → user_role_links.school_id
    (النافذة: أول الشهر الحالي UTC). عند أي فشل يُعاد 0 — لا يجوز أن
    يعطّل عطلُ التجميع خدمةَ AI لمدرسة سليمة.
    """
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        total = (
            db.session.query(db.func.coalesce(db.func.sum(AiUsageLog.total_tokens), 0))
            .join(UserRoleLink, AiUsageLog.user_id == UserRoleLink.user_id)
            .filter(
                UserRoleLink.school_id == school_id,
                UserRoleLink.role != UserRole.super_admin,
                AiUsageLog.created_at >= month_start,
            )
            .scalar()
        )
        return int(total or 0)
    except Exception:  # noqa: BLE001 — fail-open للأمانة مع التوفر
        return 0
