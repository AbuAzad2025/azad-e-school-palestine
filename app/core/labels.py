"""تسميات مشتركة مُترجَمة — مصدر واحد لعرض قيم الحالات والأدوار في الواجهة.

القيم الخام (enum values) تُخزَّن إنجليزياً في قاعدة البيانات (مثل "pending"،
"school_admin")، وهذه الوحدة هي النقطة الوحيدة لعرضها بلغة واجهة المستخدم —
ممنوع عرض القيمة الخام مباشرة في قالب (لا خلط لغوي).

الاستخدام من القوالب (مُسجَّلة كـ global):
    {{ status_label('role', user.role) }}
    {{ status_label('subscription_status', sub.status) }}
"""

from __future__ import annotations

from typing import Any

from flask_babel import gettext as _

# القيم هنا msgids عربية (المصدر) وتُترجم عند الاستدعاء لا عند الاستيراد —
# لأن flask_babel يتطلب سياق طلب لتحديد اللغة.
_LABELS: dict[str, dict[str, str]] = {
    "role": {
        "super_admin": "مدير النظام",
        "school_admin": "مدير مدرسة",
        "teacher": "معلم",
        "student": "طالب",
        "parent": "ولي أمر",
    },
    "tutoring_request_status": {
        "pending": "طلب معلق",
        "accepted": "مقبول",
        "rejected": "مرفوض",
    },
    "tutoring_mode": {
        "both": "أونلاين وحضوري",
        "online": "أونلاين",
        "offline": "حضوري",
    },
    "tutoring_session_status": {
        "requested": "مطلوبة",
        "active": "نشطة",
        "completed": "مكتملة",
        "ended": "منتهية",
        "cancelled": "ملغاة",
    },
    "tutoring_payment_status": {
        "pending": "معلق",
        "paid": "مدفوع",
        "approved": "معتمد",
        "failed": "فاشل",
    },
    "subscription_status": {
        "pending": "معلق",
        "active": "نشط",
        "expired": "منتهية",
        "cancelled": "ملغي",
        "pending_review": "بانتظار المراجعة",
    },
    "content_status": {
        "draft": "مسودة",
        "published": "منشور",
        "archived": "مؤرشف",
    },
    "attempt_status": {
        "in_progress": "قيد التنفيذ",
        "submitted": "مُسلّم",
        "graded": "مُصحّح",
    },
    "grade_appeal_status": {
        "pending": "معلق",
        "approved": "مقبول",
        "rejected": "مرفوض",
    },
}


def status_label(kind: str, value: Any) -> str:
    """إرجاع التسمية المترجمة لقيمة حالة/دور مخزّنة، أو القيمة كما هي إن لم تُعرَف.

    لا ترفض استثناءً للقيم غير المعروفة — تعرضها خاماً حتى لا تُسقط صفحة كاملة
    بسبب قيمة جديدة لم تُضَف للقاموس بعد.
    """
    raw = str(getattr(value, "value", value))
    label = _LABELS.get(kind, {}).get(raw)
    return _(label) if label else raw


def _extraction_anchor() -> None:  # pragma: no cover — مرساة استخراج فقط
    """تثبيت msgids التسميات في كتالوج babel — لا تُستدعى وقت التشغيل.

    pybabel يستخرج الاستدعاءات ذات النص الحرفي فقط، وقيم القاموس أعلاه
    متغيرات — لذا تُكرَّر هنا حرفياً ليظهرها المستخرج.
    """
    _("مدير النظام")
    _("مدير مدرسة")
    _("معلم")
    _("طالب")
    _("ولي أمر")
    _("طلب معلق")
    _("مقبول")
    _("مرفوض")
    _("أونلاين وحضوري")
    _("أونلاين")
    _("حضوري")
    _("مطلوبة")
    _("نشطة")
    _("مكتملة")
    _("منتهية")
    _("ملغاة")
    _("معلق")
    _("مدفوع")
    _("معتمد")
    _("فاشل")
    _("نشط")
    _("ملغي")
    _("بانتظار المراجعة")
    _("مسودة")
    _("منشور")
    _("مؤرشف")
    _("قيد التنفيذ")
    _("مُسلّم")
    _("مُصحّح")
