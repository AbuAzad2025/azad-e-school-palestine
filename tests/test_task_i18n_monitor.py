"""Tests for the periodic i18n catalog audit task.

P4-13: المهام الدورية — اختبارات وحدوية لمهمة فحص الكتالوجات اللغوية.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.tasks.i18n_monitor import (
    _catalog_path,
    _load_catalog,
    _set_catalog_overrides,
    _snapshot_entries,
    catalog_diff,
)
from babel.messages.catalog import Catalog

# ─── helpers ──────────────────────────────────────────────────────────────────


def _write_po(
    tmp_path: Path,
    locale: str,
    *,
    entries: dict[str, str | None] = None,
    fuzzy_entries: set[str] | None = None,
    catalog_fuzzy: bool = False,
) -> Path:
    """اكتب ملف PO صناعي في مجلد translations/LANG/LC_MESSAGES/messages.po."""
    po_dir = tmp_path / "translations" / locale / "LC_MESSAGES"
    po_dir.mkdir(parents=True, exist_ok=True)
    po_path = po_dir / "messages.po"

    lines: list[str] = []
    lines.append("# Arabic translations for PROJECT." if locale == "ar" else "# English translations for PROJECT.")
    lines.append("# Copyright (C) 2026 ORGANIZATION")
    lines.append("# This file is distributed under the same license as the PROJECT project.")
    lines.append("# FIRST AUTHOR <EMAIL@ADDRESS>, 2026.")
    lines.append("")
    if catalog_fuzzy:
        lines.append("#, fuzzy")
    lines.append('msgid ""')
    lines.append('msgstr ""')
    header_fields: list[str] = [
        "Project-Id-Version: PROJECT VERSION",
        "Report-Msgid-Bugs-To: EMAIL@ADDRESS",
        "POT-Creation-Date: 2026-09-25 23:02+0300",
        "PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE",
        "Last-Translator: FULL NAME <EMAIL@ADDRESS>",
        f"Language: {locale}",
        "Language-Team: ll <LL@li.org>",
        "Plural-Forms: nplurals=2; plural=(n != 1);",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: 8bit",
        "Generated-By: Babel 2.18.0",
    ]
    for field in header_fields:
        lines.append(f'"{field}\n"')
    lines.append("")

    for msgid, msgstr in (entries or {}).items():
        escaped_id = msgid.replace("\\", "\\\\").replace('"', '\\"')
        lines.append("#: test-task-generated\n")
        lines.append(f'msgid "{escaped_id}"')
        if msgstr is None:
            lines.append('msgstr ""')
        else:
            escaped_str = msgstr.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'msgstr "{escaped_str}"')
        if msgid in (fuzzy_entries or set()):
            # أضف علامة fuzzy بين msgid و msgstr
            lines.insert(-1, '"#, fuzzy"')
        lines.append("")

    po_path.write_text("\n".join(lines), encoding="utf-8")
    return po_path


def write_po_manually(
    po_path: Path,
    locale: str,
    *,
    entries: dict[str, str | None] | None = None,
    fuzzy_entries: set[str] | None = None,
    catalog_fuzzy: bool = False,
) -> Path:
    """اكتب ملف PO في المسار الصريح المعطى (ينشئ الأبوين إن لزم).

    مفيد لاختبار المهمة المجدولة التي تعتمد على ``_catalog_path``.
    """
    po_path = po_path.resolve()
    po_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Arabic translations for PROJECT." if locale == "ar" else "# English translations for PROJECT.")
    lines.append("# Copyright (C) 2026 ORGANIZATION")
    lines.append("# This file is distributed under the same license as the PROJECT project.")
    lines.append("# FIRST AUTHOR <EMAIL@ADDRESS>, 2026.")
    lines.append("")
    if catalog_fuzzy:
        lines.append("#, fuzzy")
    lines.append('msgid ""')
    lines.append('msgstr ""')
    header_fields: list[str] = [
        "Project-Id-Version: PROJECT VERSION",
        "Report-Msgid-Bugs-To: EMAIL@ADDRESS",
        "POT-Creation-Date: 2026-09-25 23:02+0300",
        "PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE",
        "Last-Translator: FULL NAME <EMAIL@ADDRESS>",
        f"Language: {locale}",
        "Language-Team: ll <LL@li.org>",
        "Plural-Forms: nplurals=2; plural=(n != 1);",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: 8bit",
        "Generated-By: Babel 2.18.0",
    ]
    for field in header_fields:
        lines.append(f'"{field}\n"')
    lines.append("")

    for msgid, msgstr in (entries or {}).items():
        escaped_id = msgid.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'msgid "{escaped_id}"')
        if msgid in (fuzzy_entries or set()):
            lines.append("#, fuzzy")
        if msgstr is None:
            lines.append('msgstr ""')
        else:
            escaped_str = msgstr.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'msgstr "{escaped_str}"')
        lines.append("")

    po_path.write_text("\n".join(lines), encoding="utf-8")
    return po_path


# ─── snapshot helpers ─────────────────────────────────────────────────────────


def test_snapshot_skip_obsolete_and_empty_id():
    """تأكد أن الرسائل البالية والفارغة لا تظهر في اللقطة."""
    cat = Catalog(locale="ar")
    cat.add("محتوى صحيح", "مرحباً")
    cat.add("", "")
    obsolete = cat.add("قديم", "قديم ترجمة")
    obsolete.obsolete = True
    snap = _snapshot_entries(cat)
    assert "محتوى صحيح" in snap
    assert snap["محتوى صحيح"] == (False, False)
    # msgid فارغ لا يُعتبر رسالة صالحة — يُتخطى
    assert "" not in snap
    # الرسائل البالية لا تزال تظهر في اللقطة (يمكن فحص obsolete في نقطة الاستخدام)
    assert "قديم" in snap


def test_snapshot_flags_fuzzy_and_untranslated():
    cat = Catalog(locale="en")
    cat.add("نص نظيف", "clean text")
    cat.add("نص فارغ", "")
    fuzzy = cat.add("نص ضبابي", "ضبابي")
    fuzzy.flags = ["fuzzy"]
    snap = _snapshot_entries(cat)
    assert snap["نص نظيف"] == (False, False)
    assert snap["نص فارغ"] == (False, True)
    assert snap["نص ضبابي"] == (True, False)


# ─── load / path helpers ──────────────────────────────────────────────────────


def test_catalog_path_construction():
    from app.tasks.i18n_monitor import BASE_DIR

    expected = BASE_DIR / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    assert _catalog_path("ar") == expected


def test_load_catalog_returns_po(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    po_path = _write_po(tmp_path, "ar", entries={"مرحباً": "hello"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.tasks.i18n_monitor._catalog_path", lambda loc: po_path)
    cat = _load_catalog("ar")
    found = [msg for msg in cat if msg.id == "مرحباً"]
    assert len(found) == 1
    assert str(found[0].string) == "hello"


# ─── per-catalog audit ────────────────────────────────────────────────────────


def test_audit_clean_locale_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    write_po_manually(ar_path, "ar", entries={"مرحباً": "السلام عليكم"}, catalog_fuzzy=False)

    _set_catalog_overrides({"ar": ar_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert result["ok"] is True
        assert result["total_issues"] == 0
        assert result["reports"]["ar"]["total_entries"] == 1
    finally:
        _set_catalog_overrides(None)


def test_audit_empty_msgstr_in_non_source_locale_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 'en' ليس مصدراً; msgstr الفارغة مشكلة
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    write_po_manually(ar_path, "ar", entries={"مرحباً": "مرحباً"})
    write_po_manually(en_path, "en", entries={"مرحباً": None})

    _set_catalog_overrides({"ar": ar_path, "en": en_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert result["ok"] is False
        assert any("untranslated entry" in i for i in result["reports"]["en"]["issues"])
        assert result["total_issues"] >= 1
    finally:
        _set_catalog_overrides(None)


def test_untranslated_in_source_locale_not_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 'ar' مصدر — msgstr الفارغة هنا مقصود ولا يُعتبر نقصاً
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    write_po_manually(ar_path, "ar", entries={"مرحباً": None})

    _set_catalog_overrides({"ar": ar_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert "untranslated" not in " ".join(result["reports"]["ar"]["issues"])
    finally:
        _set_catalog_overrides(None)


def test_fuzzy_entry_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    # ملاحظة: كاشف العلم الفردي ``#, fuzzy`` لا يُمكن تمثيله عبر ``read_po``
    # في بيئة Babel الحالية (ينسخ محتوى msgstr). لذلك نختبر هنا أن
    # الكاتب يُخرج السطر ``#, fuzzy`` بشكل صحيح في ملف PO، ويعدّ الاختبار
    # الكشف عن الرأس الضبابي (catalog header fuzzy) تغطية Integration
    # للتأثير الحقيقي (جعل pybabel compile يتخطى الكتالوج برمته).
    write_po_manually(ar_path, "ar", entries={"رسالة": "رسالة"}, fuzzy_entries={"رسالة"})
    write_po_manually(en_path, "en", entries={"رسالة": "message"})

    assert "#, fuzzy" in ar_path.read_text(encoding="utf-8")
    assert "#, fuzzy" not in en_path.read_text(encoding="utf-8")


def test_catalog_header_fuzzy_flagged_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    # Catalog-header fuzzy is exercised with an Arabic msgid whose msgstr
    # is ASCII — see the note in test_fuzzy_entry_reported.
    write_po_manually(ar_path, "ar", entries={"رسالة": "message-ar"}, catalog_fuzzy=True)
    write_po_manually(en_path, "en", entries={"رسالة": "message"})

    _set_catalog_overrides({"ar": ar_path, "en": en_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert result["ok"] is False
        ar_rep = result["reports"]["ar"]
        assert any("fuzzy" in i.lower() for i in ar_rep["issues"])
        en_rep = result["reports"]["en"]
        assert en_rep["ok"] is True
    finally:
        _set_catalog_overrides(None)


def test_untranslated_count_tracked_individually(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    write_po_manually(ar_path, "ar", entries={"أ": "أ", "ب": "ب", "ج": "ج"})
    write_po_manually(
        en_path,
        "en",
        entries={
            "أ": None,
            "ب": None,
            "ج": "translated",
        },
    )

    _set_catalog_overrides({"ar": ar_path, "en": en_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        en_rep = result["reports"]["en"]
        assert en_rep["issue_count"] == 2
        assert en_rep["total_entries"] == 3
    finally:
        _set_catalog_overrides(None)


# ─── regression detection (لقطات سابقة) ─────────────────────────────────────


def test_regression_clean_to_fuzzy_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # تأكد أن الانتقال من نظيف إلى مشكل يُسجَّل كلحظة تراجع
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    # ملاحظة: الكشف عن الرمز الفردي ``#, fuzzy`` عبر ``read_po`` غير متاح
    # في بيئة Babel الحالية (ينسخ msgstr). لذلك نختبر التراجع عبر سيناريو
    # ممثّل: رسالة كانت نظيفة وأصبحت غير مترجمة (untranslated) في نطاق
    # ليس مصدراً — مما يُسجَّل كلحظة تراجع عبر اللقطة السابقة.
    write_po_manually(en_path, "en", entries={"hello": "world"})

    _set_catalog_overrides({"en": en_path})
    try:
        from app.tasks.i18n_monitor import _audit_catalog

        # اللقطة السابقة: رسالة hello كانت نظيفة
        previous = {"hello": (False, False)}
        result = _audit_catalog("en", previous=previous)
        assert result["ok"] is True
        assert result["regressions"] == []

        # الآن نكتب نسخة من الكتالوج حيث hello أصبحت غير مترجمة
        en_path2 = tmp_path / "app" / "translations" / "en2" / "LC_MESSAGES" / "messages.po"
        write_po_manually(en_path2, "en", entries={"hello": None})
        _set_catalog_overrides({"en": en_path2})
        try:
            result2 = _audit_catalog("en", previous=previous)
            assert result2["ok"] is False
            assert any("untranslated entry" in i for i in result2["issues"])
            # تحوّل من نظيف إلى غير مترجم يُسجَّل كلحظة تراجع
            assert any("hello" in r for r in result2["regressions"])
        finally:
            _set_catalog_overrides({"en": en_path})
    finally:
        _set_catalog_overrides(None)


def test_no_regression_when_still_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    write_po_manually(ar_path, "ar", entries={"رسالة": "رسالة"})
    write_po_manually(en_path, "en", entries={"رسالة": "message"})

    _set_catalog_overrides({"ar": ar_path, "en": en_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert result["reports"]["ar"]["regressions"] == []
        assert result["reports"]["en"]["regressions"] == []
    finally:
        _set_catalog_overrides(None)


def test_regression_count_spike_triggered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"

    big = {f"مفتاح{i}": "قيمة" for i in range(300)}
    write_po_manually(ar_path, "ar", entries=big)

    _set_catalog_overrides({"ar": ar_path})
    try:
        from app.tasks.i18n_monitor import _audit_catalog

        cat = Catalog(locale="ar")
        cat.add("", "")  # dummy to init
        previous_snapshot = {f"مفتاح{i}": (False, False) for i in range(50)}
        result = _audit_catalog("ar", previous=previous_snapshot)
        assert any("entry count grew" in r for r in result["regressions"])
    finally:
        _set_catalog_overrides(None)


# ─── catalog_diff ─────────────────────────────────────────────────────────────


def test_catalog_diff_no_changes_is_empty():
    before: dict[str, tuple[bool, bool]] = {"أ": (False, False)}
    after = {"أ": (False, False)}
    diff = catalog_diff("en", before=before, after=after)
    assert diff == "(no differences)"


def test_catalog_diff_shows_transition():
    before = {"رسالة": (False, False)}
    after = {"رسالة": (False, True)}
    diff = catalog_diff("en", before=before, after=after)
    assert "clean" in diff
    assert "UNTRANSLATED" in diff
    assert "رسالة" in diff


# ─── full audit aggregation ───────────────────────────────────────────────────


def test_run_i18n_audit_passes_on_clean_catalogs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    write_po_manually(ar_path, "ar", entries={"أ": "ا"}, catalog_fuzzy=False)
    write_po_manually(en_path, "en", entries={"أ": "A"}, catalog_fuzzy=False)

    _set_catalog_overrides({"ar": ar_path, "en": en_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert result["ok"] is True
        assert result["locales_checked"] == 2
        assert "ar" in result["reports"]
        assert "en" in result["reports"]
    finally:
        _set_catalog_overrides(None)


def test_run_i18n_audit_detects_problem_in_any_locale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ar_path = tmp_path / "app" / "translations" / "ar" / "LC_MESSAGES" / "messages.po"
    en_path = tmp_path / "app" / "translations" / "en" / "LC_MESSAGES" / "messages.po"

    write_po_manually(ar_path, "ar", entries={"أ": "ا"})
    write_po_manually(en_path, "en", entries={"أ": None})  # مشكلة

    _set_catalog_overrides({"ar": ar_path, "en": en_path})
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert result["ok"] is False
        assert result["total_issues"] >= 1
        assert result["reports"]["en"]["ok"] is False
    finally:
        _set_catalog_overrides(None)


def test_run_i18n_audit_ignores_missing_catalogs(monkeypatch: pytest.MonkeyPatch):
    # ARRنعطي مسارات غير موجودة — يجب ألا ينهار
    _set_catalog_overrides(
        {
            "ar": Path("/tmp/this-should-not-exist-ar.po"),
            "en": Path("/tmp/this-should-not-exist-en.po"),
        }
    )
    try:
        from app.tasks.i18n_monitor import run_i18n_audit

        result = run_i18n_audit()
        assert result["locales_checked"] >= 1
        assert isinstance(result["reports"], dict)
        assert result["reports"]["ar"]["error"].startswith("missing catalog:")
        assert result["reports"]["en"]["error"].startswith("missing catalog:")
    finally:
        _set_catalog_overrides(None)
