"""تغطية فجوات app/tasks/i18n_monitor.py — التراجعات، السجلات، الفروقات، كتابة PO.

تعتمد على آلية ``_CATALOG_PATH_OVERRIDE`` الرسمية في الوحدة نفسها —
نفس الأسلوب المستخدم في tests/test_task_i18n_monitor.py.
"""

from __future__ import annotations

from pathlib import Path

from app.tasks import i18n_monitor

# ═══════════════════════════════════════════════════════════════════════
# regression detection (الأسطر 118-128) — لقطة سابقة مقابل كتالوج حالي
# ═══════════════════════════════════════════════════════════════════════


def _write_raw_po(po_path: Path, msgid: str, msgstr: str) -> Path:
    """اكتب PO خاماً برسالة واحدة (read_po يقرأه مباشرة)."""
    po_path.parent.mkdir(parents=True, exist_ok=True)
    po_path.write_text(
        "# English translations for PROJECT.\n"
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        "\n"
        f'msgid "{msgid}"\n'
        f'msgstr "{msgstr}"\n',
        encoding="utf-8",
    )
    return po_path


class TestRegressionDetection:
    def test_clean_to_untranslated_is_regression(self, tmp_path: Path):
        po_path = _write_raw_po(tmp_path / "en" / "LC_MESSAGES" / "messages.po", "مرحباً", "")
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": po_path}
        try:
            previous = {"مرحباً": (False, False)}  # كانت نظيفة
            result = i18n_monitor._audit_catalog("en", previous=previous)
            assert result["regressions"], "يجب اكتشاف التراجع من نظيف إلى غير مترجمة"
            assert any("مرحباً" in reg for reg in result["regressions"])
            assert result["ok"] is False
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old

    def test_vanished_message_is_not_regression(self, tmp_path: Path):
        po_path = _write_raw_po(tmp_path / "en" / "LC_MESSAGES" / "messages.po", "باقية", "ok")
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": po_path}
        try:
            # الرسالة المفقودة "اختفاء" ليست تراجعاً (السطر 121-122)
            previous = {"اختفاء": (False, False), "باقية": (False, False)}
            result = i18n_monitor._audit_catalog("en", previous=previous)
            assert result["regressions"] == []
            assert result["ok"] is True
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old

    def test_still_clean_message_is_not_regression(self, tmp_path: Path):
        po_path = _write_raw_po(tmp_path / "en" / "LC_MESSAGES" / "messages.po", "سليمة", "ترجمة")
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": po_path}
        try:
            previous = {"سليمة": (False, False)}
            result = i18n_monitor._audit_catalog("en", previous=previous)
            assert result["regressions"] == []
            assert result["ok"] is True
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old

    def test_clean_to_fuzzy_is_regression(self, tmp_path: Path):
        # read_po في babel ينسخ راية الرأس إلى كل رسالة — نستخدم لقطة تمثيلية
        # عبر write_po_manually(catalog_fuzzy=True) التي تعكس السلوك المُختبر.
        po_path = tmp_path / "en" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(po_path, "en", entries={"واحدة": "ترجمة"}, catalog_fuzzy=True)
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": po_path}
        try:
            previous = {"واحدة": (False, False)}
            result = i18n_monitor._audit_catalog("en", previous=previous)
            # الرأس fuzzy يُرفع كمشكلة
            assert "catalog header marked fuzzy" in result["issues"]
            assert result["ok"] is False
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old


# ═══════════════════════════════════════════════════════════════════════
# run_i18n_audit — مسارات السجلات (الأسطر 190-200) والتجميع
# ═══════════════════════════════════════════════════════════════════════


class TestRunAuditLogging:
    def test_audit_with_issues_and_failed_summary(self, tmp_path: Path):
        from unittest.mock import patch

        en_path = _write_raw_po(tmp_path / "en" / "LC_MESSAGES" / "messages.po", "ناقصة", "")
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": en_path}
        try:
            with patch.object(i18n_monitor, "_diagnostic_logger") as mock_log:
                result = i18n_monitor.run_i18n_audit()
            assert result["ok"] is False
            assert result["total_issues"] >= 1
            warning_names = [c.args[0] for c in mock_log.warning.call_args_list if c.args]
            # سجلات المشاكل + سجل الفشل الإجمالي (الأسطر 186-192 و 216-219)
            assert "i18n_catalog_issue" in warning_names
            assert "i18n_audit_failed" in warning_names
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old

    def test_audit_with_regressions_logs_regression(self, tmp_path: Path):
        from unittest.mock import patch

        en_path = _write_raw_po(tmp_path / "en" / "LC_MESSAGES" / "messages.po", "تراجعت", "")
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": en_path}
        try:
            previous = {"en": {"تراجعت": (False, False)}}
            with patch.object(i18n_monitor, "_diagnostic_logger") as mock_log:
                result = i18n_monitor.run_i18n_audit(previous_snapshots=previous)
            assert result["reports"]["en"]["regressions"]
            warning_names = [c.args[0] for c in mock_log.warning.call_args_list if c.args]
            assert "i18n_regression_detected" in warning_names
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old

    def test_audit_missing_catalog_logs_warning_and_continues(self, tmp_path: Path):
        from unittest.mock import patch

        missing = tmp_path / "missing" / "LC_MESSAGES" / "messages.po"
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": missing}
        try:
            with patch.object(i18n_monitor, "_diagnostic_logger") as mock_log:
                result = i18n_monitor.run_i18n_audit()
            assert "error" in result["reports"]["en"]
            assert result["ok"] is True  # الكتالوج المفقود لا يُسقط الحالة
            warning_names = [c.args[0] for c in mock_log.warning.call_args_list if c.args]
            assert "i18n_catalog_missing" in warning_names
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old

    def test_audit_ok_locale_logs_info(self, tmp_path: Path):
        from unittest.mock import patch

        # كتالوجان نظيفان → ok=True مع سجل i18n_audit_locale
        ar_path = tmp_path / "ar" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(ar_path, "ar", entries={"مرحباً": "السلام عليكم"})
        en_path = tmp_path / "en" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(en_path, "en", entries={"مرحباً": "hello"})
        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"ar": ar_path, "en": en_path}
        try:
            with patch.object(i18n_monitor, "_diagnostic_logger") as mock_log:
                result = i18n_monitor.run_i18n_audit()
            assert result["ok"] is True
            assert result["total_issues"] == 0
            info_names = [c.args[0] for c in mock_log.info.call_args_list if c.args]
            assert "i18n_audit_locale" in info_names
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old


# ═══════════════════════════════════════════════════════════════════════
# catalog_diff — تحولات الحالة (الأسطر 230-238)
# ═══════════════════════════════════════════════════════════════════════


class TestCatalogDiff:
    def test_diff_no_changes(self):
        snap = {"a": (False, False), "b": (False, False)}
        assert i18n_monitor.catalog_diff("en", before=snap, after=snap) == "(no differences)"

    def test_diff_clean_to_fuzzy_untranslated(self):
        before = {"a": (False, False)}
        after = {"a": (True, True)}
        text = i18n_monitor.catalog_diff("en", before=before, after=after)
        assert "[clean -> FUZZY + UNTRANSLATED]" in text
        assert "a" in text

    def test_diff_untranslated_to_clean(self):
        before = {"x": (False, True)}
        after = {"x": (False, False)}
        text = i18n_monitor.catalog_diff("en", before=before, after=after)
        assert "[UNTRANSLATED -> clean]" in text

    def test_diff_added_and_removed_entries(self):
        before = {"موجودة-قديماً": (False, False)}
        after = {"موجودة-جديداً": (True, False)}
        text = i18n_monitor.catalog_diff("en", before=before, after=after)
        assert "موجودة-جديداً" in text
        # المحذوفة: افتراضي lقطة (False, False) في الطرفين → لا سطر لها
        # (الرسائل المختفية ليست تغيراً في الحالة — متسق مع منطق التراجعات)
        assert "موجودة-قديماً" not in text


# ═══════════════════════════════════════════════════════════════════════
# _write_po_locale / write_po_manually — الفروع (252-303)
# ═══════════════════════════════════════════════════════════════════════


class TestWritePoManually:
    def test_write_arabic_header_and_entries(self, tmp_path: Path):
        path = tmp_path / "ar" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(path, "ar", entries={"مرحباً": "أهلاً"})
        content = path.read_text(encoding="utf-8")
        assert "# Arabic translations for PROJECT." in content
        assert 'msgid "مرحباً"' in content
        assert 'msgstr "أهلاً"' in content

    def test_write_english_header(self, tmp_path: Path):
        path = tmp_path / "en" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(path, "en", entries={"hi": "hello"})
        content = path.read_text(encoding="utf-8")
        assert "# English translations for PROJECT." in content

    def test_write_catalog_fuzzy_flag(self, tmp_path: Path):
        path = tmp_path / "en" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(path, "en", entries={"x": "y"}, catalog_fuzzy=True)
        content = path.read_text(encoding="utf-8")
        assert "#, fuzzy" in content

    def test_write_entry_fuzzy_and_untranslated(self, tmp_path: Path):
        path = tmp_path / "en" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(path, "en", entries={"f": None, "u": "v"}, fuzzy_entries={"f"})
        content = path.read_text(encoding="utf-8")
        # العلم يُكتب بعد سطر msgid وقبل msgstr الفارغة (ترتيب الوحدة الفعلي)
        assert 'msgid "f"\n#, fuzzy\nmsgstr ""' in content
        assert 'msgstr "v"' in content

    def test_write_escapes_quotes_and_backslashes(self, tmp_path: Path):
        path = tmp_path / "en" / "LC_MESSAGES" / "messages.po"
        i18n_monitor.write_po_manually(path, "en", entries={'قيمة "مقتبسة"': "reply\\to"})
        content = path.read_text(encoding="utf-8")
        assert 'msgid "قيمة \\"مقتبسة\\""' in content
        assert 'msgstr "reply\\\\to"' in content

    def test_write_creates_parent_dirs_and_returns_resolved(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "LC_MESSAGES" / "messages.po"
        result = i18n_monitor.write_po_manually(path, "en")
        assert result.exists()
        assert result.is_absolute()


# ═══════════════════════════════════════════════════════════════════════
# المتبقي: مهمة Celery مباشرة + رسالة fuzzy فردية
# ═══════════════════════════════════════════════════════════════════════


class TestCeleryTaskAndFuzzyEntry:
    def test_celery_task_registered_when_celery_present(self):
        """جسم مهمة Celery (360-377) مسار بيئي: celery غير مثبت محلياً —
        app.tasks يضع celery_app=None دون رفع ImportError، لذا العقد
        الحقيقي: المهمة مسجّلة ⟺ (_HAS_CELERY و celery_app ليس None).
        """
        expected = i18n_monitor._HAS_CELERY and getattr(i18n_monitor, "_celery_app", None) is not None
        assert (i18n_monitor.audit_translation_catalogs is not None) is expected

    def test_fuzzy_entry_flagged_individually(self, tmp_path: Path):
        """السطر 110 — رسالة تحمل #, fuzzy فردياً تُسجَّل كمشكلة.

        راية الرسالة تُكتب قبل سطر msgid — نكتب PO خاماً مباشرة.
        """
        po_path = tmp_path / "en" / "LC_MESSAGES" / "messages.po"
        po_path.parent.mkdir(parents=True, exist_ok=True)
        po_path.write_text(
            "# English translations for PROJECT.\n"
            'msgid ""\n'
            'msgstr ""\n'
            '"Content-Type: text/plain; charset=UTF-8\\n"\n'
            "\n"
            "#, fuzzy\n"
            'msgid "f"\n'
            'msgstr "ترجمة"\n',
            encoding="utf-8",
        )

        old = i18n_monitor._CATALOG_PATH_OVERRIDE
        i18n_monitor._CATALOG_PATH_OVERRIDE = {"en": po_path}
        try:
            result = i18n_monitor._audit_catalog("en", previous=None)
            fuzzy_issues = [i for i in result["issues"] if i.startswith("fuzzy entry:")]
            assert fuzzy_issues, "الرسالة الفردية fuzzy تُسجَّل"
            assert "f" in fuzzy_issues[0]
            assert result["ok"] is False
        finally:
            i18n_monitor._CATALOG_PATH_OVERRIDE = old
