"""توليد PDF عربي — بنية تحتية مشتركة لكل المهام الخلفية والخدمات.

التصميم (P4-07 → تنفيذ حقيقي):
    - المحرك: reportlab (platypus) مباشرة — لا وسيط HTML/CSS.
      (xhtml2pdf/pisa لا يدعم خطوط TTF عربية بشكل موثوق: font-family
      لا يُحلّ من سجل reportlab، و@font-face يفشل على Windows بملفات
      temp مقفولة — لذلك البناء المباشر هو المسار المستقر.)
    - التشكيل: reportlab لا يطبّق تشكيل العربية (joining) ولا الاتجاه،
      لذا تُمرَّر النصوص عبر arabic_reshaper + python-bidi قبل الرسم
      (المكتبتان مثبّتان بالفعل). اختيارية: عند غيابهما يُعرض النص كما هو.
    - الخط: TTF عربي يُكتشف من إعداد التطبيق ثم مجلدات النظام
      (Arial/Tahoma على Windows، DejaVu على لينكس)، مع fallback Helvetica.

الاستخدام:
    font = register_arabic_font()
    data = shape_arabic_deep(grade_data)
    doc, story = blank_pdf_document()
    story_title(story, "التقرير", font)
    story_table(story, rows, widths, font)
    path = write_pdf_file("report_cards", "report_1", build_pdf_bytes(doc, story), school_id=1)

دوال هذه الوحدة تعمل بلا سياق طلب (مهام Celery) ولا تعتمد على
request/session — البيانات تُمرَّر كاملة كوسائط.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# أسماء ملفات خطوط TTF المجرَّبة لدعم المحارف العربية (تُفحص بالترتيب،
# والمطابقة غير حساسة لحالة الأحرف لأن أنظمة لينكس حساسة للحالة)
_ARABIC_FONT_CANDIDATES: tuple[str, ...] = (
    "amiri-regular.ttf",
    "notonaskharabic-regular.ttf",
    "notonaskharabic.ttf",
    "tahoma.ttf",
    "arial.ttf",
    "dejavusans.ttf",
)

_DIRS_EXTRA = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts", "/usr/local/share/fonts")

# بديل أخير مضمّن مع reportlab — لا دعم عربي، لكن المهمة لا تنهار
_FALLBACK_FONT = "Helvetica"

_ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")

_font_cache: dict[str, str] = {}


def _iter_font_dirs() -> list[str]:
    """مجلدات البحث عن الخطوط: إعداد التطبيق + مجلدات النظام."""
    dirs: list[str] = []
    try:
        from flask import current_app

        configured = current_app.config.get("PDF_FONT_DIR")
        if configured:
            dirs.append(str(configured))
    except RuntimeError:
        pass  # بلا سياق تطبيق (استدعاء مباشر/اختبار)
    dirs.extend(_DIRS_EXTRA)
    if os.name == "nt":
        dirs.append(r"C:\Windows\Fonts")
    return dirs


def font_readiness() -> dict:
    """تقرير جاهزية الخط العربي لتوليد PDF — يُستخدم في /health/deep.

    فحص قراءة فقط: لا يسجّل الخط في reportlab ولا يمس الكاش، فيمكن
    استدعاؤه من نقاط الصحة دون آثار جانبية.
    """
    font_path = _find_font_file()
    if font_path:
        return {"status": "ok", "font_file": font_path}
    return {
        "status": "warning",
        "font_file": None,
        "hint": (
            "set PDF_FONT_DIR or install an Arabic TTF — "
            "fallback Helvetica has no Arabic glyphs (log: pdf_font_fallback)"
        ),
    }


def _find_font_file() -> str | None:
    """أول ملف خط عربي موجود فعلياً على القرص (مطابقة غير حساسة للحالة)."""
    for font_dir in _iter_font_dirs():
        if not os.path.isdir(font_dir):
            continue
        try:
            entries = {name.lower(): name for name in os.listdir(font_dir)}
        except OSError:
            continue
        for candidate in _ARABIC_FONT_CANDIDATES:
            actual = entries.get(candidate)
            if actual:
                return os.path.join(font_dir, actual)
    return None


def register_arabic_font() -> str:
    """تسجيل أول خط عربي متاح في reportlab وإرجاع اسمه المنطقي.

    النتيجة تُخزَّن مؤقتاً لكل عملية (المهام تستدعي هذا كثيراً).
    عند عدم وجود أي خط عربي تُعاد Helvetica مع تحذير — لا انهيار.
    """
    if _font_cache:
        return next(iter(_font_cache.values()))

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_path = _find_font_file()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("AzadArabic", font_path))
            _font_cache["AzadArabic"] = "AzadArabic"
            logger.info("pdf_font_registered", font=font_path)
            return "AzadArabic"
        except Exception:  # noqa: BLE001 — خط تالف؟ جرّب الـ fallback
            logger.warning("pdf_font_register_failed", font=font_path)

    logger.warning("pdf_font_fallback", fallback=_FALLBACK_FONT)
    _font_cache[_FALLBACK_FONT] = _FALLBACK_FONT
    return _FALLBACK_FONT


def shape_arabic(text: str) -> str:
    """تشكيل نص عربي للعرض الصحيح في reportlab (joining + bidi).

    يجب استدعاؤها لكل نص يُرسم — reportlab يرسم محارف معزولة بلا ترتيب
    بصري صحيح دونها. النص اللاتيني/الأرقام تمر دون تغيير جوهري.
    """
    if not text:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


def shape_arabic_deep(value: Any) -> Any:
    """تشكيل كل نص عربي داخل بنية متداخلة (dict/list/tuple/set).

    يُستخدم قبل تمرير بيانات قاعدة البيانات إلى مولّدات PDF: أسماء
    الطلاب، أسماء الأقسام/البنود، التقديرات الحرفية... إلخ.
    Non-strings تعود كما هي؛ النصوص بلا حروف عربية تمر دون معالجة.
    """
    if isinstance(value, str):
        return shape_arabic(value) if _ARABIC_CHAR_RE.search(value) else value
    if isinstance(value, dict):
        return {k: shape_arabic_deep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return type(value)(shape_arabic_deep(v) for v in value)
    return value


def pdf_output_dir(school_id: int, subdir: str) -> str:
    """مجلد المخرجات المحمي: instance/uploads/generated/<subdir>/<school_id>.

    خارج المجلد العام (D7) — تُخدم الملفات عبر routes مُصرَّح بها فقط.
    """
    from flask import current_app

    base = current_app.config.get(
        "UPLOAD_FOLDER",
        os.path.join("instance", "uploads"),
    )
    path = os.path.join(str(base), "generated", subdir, str(school_id))
    os.makedirs(path, exist_ok=True)
    return path


def ctx_school_id() -> int:
    """school_id من سياق الطلب إن توفر — 0 خارج الطلب/للمشرف العام."""
    try:
        from flask import has_request_context

        if has_request_context():
            from app.core.tenancy import current_school_id

            return current_school_id() or 0
    except RuntimeError:
        pass
    return 0


def write_pdf_file(
    subdir: str,
    filename_stem: str,
    data: bytes,
    school_id: int | None = None,
) -> str:
    """كتابة bytes على القرص ذرّياً — لا يبقى ملف نصف مكتوب عند الفشل.

    Args:
        subdir: مجلد فرعي تحت generated/ (مثل "report_cards").
        filename_stem: اسم الملف بلا امتداد/طابع زمني.
        data: محتوى PDF الخام.
        school_id: المدرسة (تينانتس) — None = استنتاج من سياق الطلب.

    Returns:
        المسار النهائي للملف المكتوب.
    """
    resolved_school = school_id if school_id is not None else ctx_school_id()
    out_dir = pdf_output_dir(resolved_school, subdir)
    filename = f"{filename_stem}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.pdf"
    final_path = os.path.join(out_dir, filename)

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=out_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, final_path)  # ذرّية
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    logger.info("pdf_written", path=final_path, size=len(data))
    return final_path


# ─── بناء المستندات (platypus) ────────────────────────────────────────


def blank_pdf_document() -> tuple[Any, list]:
    """(SimpleDocTemplate, story) جاهزان لبناء صفحة A4 — نقطة موحّدة للهوية.

    استدعِ مساعدات story_* لتعبئة القصة ثم build_pdf_bytes(doc, story).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(
        BytesIO(),
        pagesize=A4,
        topMargin=50,
        bottomMargin=50,
        leftMargin=40,
        rightMargin=40,
        title="Azad E-School Report",
    )
    return doc, []


def build_pdf_bytes(doc: Any, story: list) -> bytes:
    """بناء القصة داخل القالب وإرجاع bytes جاهزة للكتابة."""
    doc.build(story)
    buffer = getattr(doc, "filename", None)
    if not isinstance(buffer, BytesIO):
        raise TypeError("doc was not created by blank_pdf_document")
    return buffer.getvalue()


def story_title(story: list, text: str, font: str, size: int = 16) -> None:
    """عنوان رئيسي — محاذاة يمين (RTL)."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    style = ParagraphStyle("pdfTitle", fontName=font, fontSize=size, alignment=2, spaceAfter=6)
    story.append(Paragraph(text, style))


def story_subtitle(story: list, text: str, font: str) -> None:
    """عنوان فرعي/سطر وصف — محاذاة يمين (RTL)."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    style = ParagraphStyle("pdfSub", fontName=font, fontSize=10, alignment=2, spaceAfter=12)
    story.append(Paragraph(text, style))


def story_meta(story: list, text: str) -> None:
    """سطر بيانات LTR (أرقام/معرّفات/تواريخ) بخط لاتيني — بلا خلط اتجاهات.

    خلط RTL + أرقام في فقرة واحدة يربك محركات العرض/الاستخراج، لذا تُفصل
    البيانات الرقمية في سطر مستقل يسار-إلى-يمين.
    """
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    style = ParagraphStyle(
        "pdfMeta",
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.HexColor("#666666"),
        alignment=0,
        spaceAfter=10,
    )
    story.append(Paragraph(text, style))


def story_table(story: list, rows: list[list[str]], widths: list[float], font: str) -> None:
    """جدول بهوية المنصة (ترويسة #014e7c، صفوف متناوبة) + مسافة بعده."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Spacer, Table, TableStyle

    t = Table(rows, colWidths=widths, hAlign="RIGHT")
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("FONTNAME", (0, 0), (-1, 0), font),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#014e7c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")]),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(6 * mm, 6 * mm))


__all__ = [
    "blank_pdf_document",
    "build_pdf_bytes",
    "ctx_school_id",
    "font_readiness",
    "pdf_output_dir",
    "register_arabic_font",
    "shape_arabic",
    "shape_arabic_deep",
    "story_meta",
    "story_subtitle",
    "story_table",
    "story_title",
    "write_pdf_file",
]
