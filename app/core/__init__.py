"""النواة المركزية — نقاط استدعاء موحّدة بلا تكرار.

كل الطبقات المشتركة تُعاد تصديرها من هنا؛ هذه النقطة الوحيدة الموصى بها
للاستيراد في modules (وخدمات base تعيد تصدير tx لكل services).
"""

from .context import register as register_context
from .db import TxError, tx
from .i18n import _
from .logging import get_correlation_id, get_logger
from .permissions import (
    class_access_required,
    class_teach_required,
    parent_of_required,
    role_required,
    student_only,
)
from .security import hash_password, verify_password
from .tenancy import get_school_or_404, scope_by_school, tenant_scope
from .tokens import make_activation_token, make_reset_token, make_token, read_reset_token, read_token
from .uploads import allowed_extension, save_upload

__all__ = [
    "_",
    "TxError",
    "allowed_extension",
    "get_correlation_id",
    "get_logger",
    "get_school_or_404",
    "hash_password",
    "make_activation_token",
    "make_reset_token",
    "make_token",
    "read_reset_token",
    "read_token",
    "register_context",
    "class_access_required",
    "class_teach_required",
    "parent_of_required",
    "role_required",
    "student_only",
    "save_upload",
    "scope_by_school",
    "tenant_scope",
    "tx",
    "verify_password",
]
