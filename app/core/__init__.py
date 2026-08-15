"""النواة المركزية — نقاط استدعاء موحّدة بلا تكرار.

كل الطبقات المشتركة تُعاد تصديرها من هنا؛ هذه النقطة الوحيدة الموصى بها
للاستيراد في modules (وخدمات base تعيد تصدير tx لكل services).
"""
from .context import register as register_context
from .db import TxError, tx
from .permissions import role_required
from .security import hash_password, verify_password
from .tenancy import get_school_or_404, scope_by_school, tenant_scope
from .tokens import make_activation_token, read_token

__all__ = [
    "TxError",
    "get_school_or_404",
    "hash_password",
    "make_activation_token",
    "read_token",
    "register_context",
    "role_required",
    "scope_by_school",
    "tenant_scope",
    "tx",
    "verify_password",
]
