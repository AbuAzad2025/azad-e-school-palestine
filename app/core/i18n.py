"""غلاف i18n مركزي — gettext آمن خارج سياق الطلب.

الخدمات تُستدعى أحياناً بلا طلب HTTP (سكربتات الصيانة، الاختبارات، المهام الدورية)،
و`flask_babel.get_locale()` يرفض العمل خارج السياق. هذا الغلاف يترجم عند توفر
بيئة Flask ويعيد النص المصدر منسّقاً بدل الانهيار عند غيابها.
"""

from __future__ import annotations

from typing import Any

from flask import has_request_context
from flask_babel import gettext as _babel_gettext


def _(msgid: str, **variables: Any) -> str:
    """ترجمة رسالة مع placeholders مسماة، بأمان داخل أو خارج سياق الطلب.

    ملاحظة: gettext يطبق %-تنسيق على msgid دائماً؛ تمرير variables فارغة
    (مثل رسالة تحتوي "%" حرفية) يسبب ValueError — لذا لا نمررها إلا عند وجودها.
    """
    if not has_request_context():
        # خارج سياق الطلب (مهام دورية/سكربتات/اختبارات خدمات) لا يوجد لغوي
        # محدد من الكوكيز — نعيد المصدر منسّقاً يدوياً بدل الانهيار.
        return msgid % variables if variables else msgid
    if variables:
        return _babel_gettext(msgid, **variables)
    return _babel_gettext(msgid)
