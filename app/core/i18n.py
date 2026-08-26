"""غلاف i18n مركزي — gettext آمن خارج سياق الطلب.

الخدمات تُستدعى أحياناً بلا طلب HTTP (سكربتات الصيانة، الاختبارات، المهام الدورية)،
و`flask_babel.get_locale()` يرفض العمل خارج السياق. هذا الغلاف يترجم عند توفر
بيئة Flask ويعيد النص المصدر منسّقاً بدل الانهيار عند غيابها.
"""

from __future__ import annotations

from typing import Any

from flask_babel import gettext as _babel_gettext


def _(msgid: str, **variables: Any) -> str:
    """ترجمة رسالة مع placeholders مسماة، بأمان داخل أو خارج سياق الطلب."""
    try:
        return _babel_gettext(msgid, **variables)
    except RuntimeError:
        # لا سياق Flask (سكربت/اختبار) — نعيد المصدر مع التنسيق فقط
        return msgid % variables if variables else msgid
