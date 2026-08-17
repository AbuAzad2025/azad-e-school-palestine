"""أساس الخدمات — إعادة تصدير نمط الذرّية من النواة (لا تكرار للمنطق).

يُستورد من هنا في services للحفاظ على الواجهة، بينما المنطق في app/core/db.py.
"""

from app.core.db import TxError, tx

__all__ = ["TxError", "tx"]
