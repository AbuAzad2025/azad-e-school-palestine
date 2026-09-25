"""اختبارات app/core/pdf.py — الخط العربي، التشكيل، الكتابة الذرّية.

تغطي: register_arabic_font (اكتشاف/تخزين مؤقت/fallback)، shape_arabic
(تشكيل + bidi)، shape_arabic_deep (بنى متداخلة)، write_pdf_file (كتابة
ذرّية + تنظيف عند الفشل + تينانتس صريح)، pdf_output_dir، blank_pdf_document،
ctx_school_id خارج سياق الطلب، وتضمين محارف عربية حقيقية في PDF مُنتَج.
"""

from __future__ import annotations

import os

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# register_arabic_font
# ═══════════════════════════════════════════════════════════════════════════


def test_register_arabic_font_returns_logical_name():
    from app.core.pdf import register_arabic_font

    name = register_arabic_font()
    assert name in {"AzadArabic", "Helvetica"}


def test_register_arabic_font_is_cached():
    from app.core import pdf

    first = pdf.register_arabic_font()
    second = pdf.register_arabic_font()
    assert first == second
    assert pdf._font_cache  # مخزّن مؤقتاً لكل عملية


def test_register_arabic_font_fallback_when_no_font_found(monkeypatch):
    """لا خطوط متاحة → Helvetica مع تحذير، بلا انهيار."""
    from app.core import pdf

    monkeypatch.setattr(pdf, "_font_cache", {})
    monkeypatch.setattr(pdf, "_find_font_file", lambda: None)

    from reportlab.pdfbase import pdfmetrics

    name = pdf.register_arabic_font()
    assert name == "Helvetica"
    # تنظيف: أعد الخط الحقيقي لبقية الاختبارات
    monkeypatch.setattr(pdf, "_font_cache", {})
    pdf.register_arabic_font()
    assert pdfmetrics.getFont("AzadArabic") is not None


# ═══════════════════════════════════════════════════════════════════════════
# shape_arabic / shape_arabic_deep
# ═══════════════════════════════════════════════════════════════════════════


def test_shape_arabic_reshapes_arabic_text():
    """مع توفر arabic_reshaper: الناتج مشكّل (محارف presentation forms)."""
    from app.core.pdf import shape_arabic

    pytest.importorskip("arabic_reshaper")
    out = shape_arabic("مرحبا")
    assert out != "مرحبا"  # تغيّر التشكيل
    assert any("\ufb50" <= ch <= "\ufeff" for ch in out)  # presentation forms


def test_shape_arabic_latin_passthrough():
    from app.core.pdf import shape_arabic

    assert shape_arabic("Hello 123") == "Hello 123"
    assert shape_arabic("") == ""


def test_shape_arabic_graceful_without_libs(monkeypatch):
    """غياب المكتبتين → النص كما هو (تدهور مقبول بلا انهيار)."""
    import builtins

    from app.core import pdf

    real_import = builtins.__import__

    def _blocked(name, *a, **kw):
        if name.startswith("arabic_reshaper") or name == "bidi":
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    assert pdf.shape_arabic("نص") == "نص"


def test_shape_arabic_deep_nested_structures():
    from app.core.pdf import shape_arabic_deep

    data = {
        "name": "أحمد",
        "items": ["الرياضيات", 95.5, ("ممتاز",)],
        "latin": "Math",
        "n": 5,
    }
    out = shape_arabic_deep(data)

    assert out["latin"] == "Math"  # لاتيني يمر كما هو
    assert out["n"] == 5
    assert isinstance(out["items"][2], tuple)  # النوع محفوظ
    if out["name"] != "أحمد":  # تم التشكيل
        assert any("\ufb50" <= ch <= "\ufeff" for ch in out["name"])
    else:
        pytest.importorskip("arabic_reshaper")


def test_shape_arabic_deep_scalars_passthrough():
    from app.core.pdf import shape_arabic_deep

    assert shape_arabic_deep(None) is None
    assert shape_arabic_deep(42) == 42
    assert shape_arabic_deep(3.14) == 3.14
    assert shape_arabic_deep(True) is True


# ═══════════════════════════════════════════════════════════════════════════
# write_pdf_file — الكتابة الذرّية
# ═══════════════════════════════════════════════════════════════════════════


def test_write_pdf_file_writes_atomic_pdf(app, tmp_path, monkeypatch):
    from app.core.pdf import write_pdf_file

    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
    with app.app_context():
        path = write_pdf_file("report_cards", "report_1_2", b"%PDF-1.4 fake", school_id=7)

    assert path.endswith(".pdf")
    assert os.sep + "7" + os.sep in path  # تينانتس المدرسة في المسار
    assert "report_1_2_" in path
    with open(path, "rb") as f:
        assert f.read() == b"%PDF-1.4 fake"
    # لا ملفات مؤقتة متبقية (ذرّية)
    assert len(os.listdir(os.path.dirname(path))) == 1


def test_write_pdf_file_cleans_up_on_failure(app, tmp_path, monkeypatch):
    """فشل النقل → ينتشر الخطأ ولا يبقى ملف ناقص."""
    from app.core import pdf

    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))

    with app.app_context():
        out_dir = pdf.pdf_output_dir(3, "invoices")
        real_replace = os.replace

        def _boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(pdf.os, "replace", _boom)
        with pytest.raises(OSError, match="disk full"):
            pdf.write_pdf_file("invoices", "inv_1", b"%PDF-x", school_id=3)

        monkeypatch.setattr(pdf.os, "replace", real_replace)
    assert os.listdir(out_dir) == []  # نظيف — لا بقايا


def test_write_pdf_file_infers_school_from_context(app, tmp_path, monkeypatch):
    """بلا school_id صريح خارج طلب → 0 (مجلد عام للمشرف)."""
    from app.core.pdf import write_pdf_file

    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
    with app.app_context():
        path = write_pdf_file("reports", "no_school", b"%PDF-1.4", school_id=None)
    assert os.sep + "0" + os.sep in path


# ═══════════════════════════════════════════════════════════════════════════
# pdf_output_dir / blank_pdf_document / ctx_school_id
# ═══════════════════════════════════════════════════════════════════════════


def test_pdf_output_dir_creates_nested_dirs(app, tmp_path, monkeypatch):
    from app.core.pdf import pdf_output_dir

    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
    with app.app_context():
        path = pdf_output_dir(9, "class_reports")
    assert os.path.isdir(path)
    assert "generated" in path and "class_reports" in path and "9" in path


def test_blank_pdf_document_builds_valid_pdf():
    from app.core.pdf import blank_pdf_document, build_pdf_bytes
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph

    doc, story = blank_pdf_document()
    story.append(Paragraph("hello", getSampleStyleSheet()["Normal"]))
    data = build_pdf_bytes(doc, story)
    assert data.startswith(b"%PDF-")
    assert len(data) > 500


def test_build_pdf_bytes_rejects_foreign_doc():
    """build_pdf_bytes يرفض قالباً لم يُنشأ عبر blank_pdf_document."""
    from unittest.mock import MagicMock

    from app.core.pdf import build_pdf_bytes

    doc = MagicMock()
    doc.filename = "not-a-buffer.pdf"

    with pytest.raises(TypeError):
        build_pdf_bytes(doc, [])


def test_ctx_school_id_outside_request_is_zero():
    from app.core.pdf import ctx_school_id

    assert ctx_school_id() == 0


def test_font_readiness_ok(app, tmp_path, monkeypatch):
    """خط موجود في مجلد مضبوط → status ok مع مسار الملف."""
    from app.core.pdf import font_readiness

    monkeypatch.setitem(app.config, "PDF_FONT_DIR", str(tmp_path))
    (tmp_path / "amiri-regular.ttf").write_bytes(b"x")  # الاكتشاف بالاسم فقط
    with app.app_context():
        report = font_readiness()
    assert report["status"] == "ok"
    assert report["font_file"] and "amiri" in report["font_file"].lower()


def test_font_readiness_warning_when_missing(app, tmp_path, monkeypatch):
    """لا خط عربي في أي مجلد → warning مع hint قابلة للتنفيذ."""
    from app.core import pdf as pdf_mod
    from app.core.pdf import font_readiness

    monkeypatch.setitem(app.config, "PDF_FONT_DIR", str(tmp_path))
    real_iter = pdf_mod._iter_font_dirs

    def _no_fonts():
        return []  # عزل: نتجاهل مجلدات النظام المضيفة

    monkeypatch.setattr(pdf_mod, "_iter_font_dirs", _no_fonts)
    real_iter()  # sanity: النسخة الحقيقية لا تُلغي الاكتشاف هنا
    with app.app_context():
        report = font_readiness()
    assert report["status"] == "warning"
    assert report["font_file"] is None
    assert "PDF_FONT_DIR" in report["hint"]


# ═══════════════════════════════════════════════════════════════════════════
# تكامل: محارف عربية حقيقية مضمّنة في PDF مُنتَج
# ═══════════════════════════════════════════════════════════════════════════


def test_pdf_embeds_shaped_arabic_glyphs():
    """الخط العربي مدمج والتشكيل ظاهر في PDF نهائي (font != fallback)."""
    pytest.importorskip("pypdf")  # فحص عميق للاستخراج — اختياري في CI

    from app.core.pdf import (
        blank_pdf_document,
        build_pdf_bytes,
        register_arabic_font,
        shape_arabic,
        story_title,
    )

    font = register_arabic_font()
    if font == "Helvetica":
        pytest.skip("لا يوجد خط TTF عربي على هذا المضيف — موثق: يُشترى/يُثبّت في الإنتاج")

    doc, story = blank_pdf_document()
    story_title(story, shape_arabic("بطاقة درجات"), font)
    data = build_pdf_bytes(doc, story)

    import io

    from pypdf import PdfReader

    text = PdfReader(io.BytesIO(data)).pages[0].extract_text()
    presentation = [ch for ch in text if "\ufb50" <= ch <= "\ufdff" or "\ufe70" <= ch <= "\ufeff"]
    assert presentation, "المحارف العربية المشكّلة يجب أن تُدمج في الـ PDF"
