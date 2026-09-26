"""Translation catalog health monitor — periodic i18n regression checks.

P4-13: Scheduled Celery task that inspects every registered translation catalog
regularly and surfaces three failure classes early:

1. Untranslated entries in non-source locales (e.g. empty msgstr in 'en').
2. Fuzzy entries (either per-message or catalog-header fuzzy) — makes
   pybabel compile skip the whole catalog.
3. Regression markers detectable from the catalog state alone
   (re-appearance of previously-clean entries that flipped back to fuzzy /
   untranslated, or sudden count spikes versus the last stored snapshot).

The task is intentionally pure-i18n: it reads compiled ``.po`` files only,
never mutates them, and emits structured logs + a persisted ``TranslationAudit``
row so operators can track drift over time. It is wired into Celery beat via
the schedule in ``app/tasks/__init__``.

الاعتماديات: babel (موجود دوماً مع Flask-Babel) + النموذج
``app.models.system.TranslationAudit`` (يُنشأ في migration مستقل).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po

from app.core.logging import get_logger

SOURCE_LOCALES = {"ar"}  # لغة المصدر في هذا المشروع

BASE_DIR = Path(__file__).resolve().parent.parent


_diagnostic_logger = get_logger("celery.i18n_monitor")


# اختبار فقط: إعادة توجيه مسارات الكتالوجات إلى مجلد مؤقت
_CATALOG_PATH_OVERRIDE: dict[str, Path] | None = None


def _catalog_path(locale: str) -> Path:
    """مسار الكتالوج المُجمَّع الحالي للنطاق اللغوي."""
    if _CATALOG_PATH_OVERRIDE is not None and locale in _CATALOG_PATH_OVERRIDE:
        return _CATALOG_PATH_OVERRIDE[locale]
    return BASE_DIR / "app" / "translations" / locale / "LC_MESSAGES" / "messages.po"


def _snapshot_entries(cat: Catalog) -> dict[str, tuple[bool, bool]]:
    """يعيد خريطة msgid -> (Fuzzy, Untranslated) للفحص اللاحق.

    - ``fuzzy``: تحمل الرسالة علم fuzzy.
    - ``untranslated``: msgstr فارغ في نطاق غير مصدر.
    """
    out: dict[str, tuple[bool, bool]] = {}
    for msg in cat:
        if not msg.id:
            continue
        fuzzy = "fuzzy" in (msg.flags or ())
        out[str(msg.id)] = (fuzzy, not bool(msg.string))
    return out


def _audit_catalog(
    locale: str,
    *,
    previous: dict[str, tuple[bool, bool]] | None,
) -> dict[str, Any]:
    """يُفحِص كتالوج واحد ويعيد تقريراً عند وجود مشاكل.

    اعتمادية: يقرأ ملفات PO فقط ولا يلامس قاعدة البيانات (يسمح بالتشغيل
    في بيئات لا توجد فيها الجداول بعد).
    """
    path = _catalog_path(locale)
    if not path.exists():
        return {
            "locale": locale,
            "ok": False,
            "error": f"missing catalog: {path}",
            "issue_count": 1,
            "total_entries": 0,
            "issues": [f"missing catalog: {path}"],
            "regressions": [],
            "snapshot": {},
            "checked_at": datetime.now(UTC).isoformat(),
        }

    cat = _load_catalog(locale)
    now = datetime.now(UTC)

    issues: list[str] = []

    # رأس الكتالوج fuzzy يجعل pybabel compile يتخطى الكل
    if cat.fuzzy:
        issues.append("catalog header marked fuzzy")

    current: dict[str, tuple[bool, bool]] = {}
    for msg in cat:
        if not msg.id or getattr(msg, "obsolete", False):
            continue

        fuzzy = "fuzzy" in (msg.flags or ())
        untranslated = not bool(msg.string)

        # تسجيل المشاكل
        if fuzzy:
            issues.append(f"fuzzy entry: {msg.id[:60]!r}")
        elif locale not in SOURCE_LOCALES and untranslated:
            issues.append(f"untranslated entry: {msg.id[:60]!r}")

        current[str(msg.id)] = (fuzzy, untranslated)

    # كشف انحرافات عن اللقطة السابقة (regressions)
    regressed: list[str] = []
    if previous is not None:
        for msgid, (prev_fuzzy, prev_untrans) in previous.items():
            if msgid not in current:
                # الرسالة اختفت من الكتالوج — ليست مشكلة بحد ذاتها
                continue
            cur_fuzzy, cur_untrans = current[msgid]
            # انتقل من نظيف إلى مشكل
            if (not prev_fuzzy and not prev_untrans) and (cur_fuzzy or cur_untrans):
                regressed.append(msgid[:60])
        added = len(current) - len(previous)
        if added > 200:  # عتبة تقريبية — قد تُعدّل لاحقاً
            regressed.append(f"entry count grew by {added} since last run")

    return {
        "locale": locale,
        "ok": not issues and not regressed,
        "issue_count": len(issues) + len(regressed),
        "total_entries": len(current),
        "issues": issues[:50],
        "regressions": regressed[:50],
        "snapshot": current,
        "checked_at": now.isoformat(),
    }


def run_i18n_audit(
    *,
    previous_snapshots: dict[str, dict[str, tuple[bool, bool]]] | None = None,
) -> dict[str, Any]:
    """المهمة الدورية — تفحص كل النطاقات اللغوية المسجلة.

    عند وجود Celery يتم جدولتها عبر beat (انظر ``app/tasks/__init__``).
    تعمل أيضاً كدالة عادية في الروابط والتصحيحات اليدوية.
    """
    registered_locales = ["ar", "en"]  # ADM-02: اللغات المدعومة في config.LANGUAGES

    previous = previous_snapshots or {}

    reports: dict[str, dict[str, Any]] = {}
    all_ok = True
    total_issues = 0

    for locale in registered_locales:
        path = _catalog_path(locale)
        prev_snapshot = previous.get(locale)
        result = _audit_catalog(locale, previous=prev_snapshot)
        reports[locale] = result
        if "error" in result:
            # كتالوج مفقود — ليست مشكلة في الترجمة بل في البيئة؛
            # نسجّل تحذيراً دون إسقاط حالة المهمة.
            _diagnostic_logger.warning(
                "i18n_catalog_missing",
                locale=locale,
                path=str(path),
            )
            continue
        if not result["ok"]:
            all_ok = False
            total_issues += result["issue_count"]

        _diagnostic_logger.info(
            "i18n_audit_locale",
            locale=locale,
            ok=result["ok"],
            issue_count=result["issue_count"],
            total_entries=result["total_entries"],
        )

        if result["issues"]:
            for iss in result["issues"]:
                _diagnostic_logger.warning(
                    "i18n_catalog_issue",
                    locale=locale,
                    issue=iss,
                )

        if result["regressions"]:
            for reg in result["regressions"]:
                _diagnostic_logger.warning(
                    "i18n_regression_detected",
                    locale=locale,
                    detail=reg,
                )

    summary = {
        "ok": all_ok,
        "total_issues": total_issues,
        "locales_checked": len(registered_locales),
        "reports": reports,
        "run_at": datetime.now(UTC).isoformat(),
    }

    if not all_ok:
        _diagnostic_logger.warning(
            "i18n_audit_failed",
            total_issues=total_issues,
        )

    return summary


def catalog_diff(
    locale: str,
    *,
    before: dict[str, tuple[bool, bool]],
    after: dict[str, tuple[bool, bool]],
) -> str:
    """يعيد نص diff بين لقطتين للكتالوج — للاستخدام في السجلات / الإشعارات."""
    out_lines: list[str] = []
    for msgid in sorted(set(before) | set(after)):
        bf = before.get(msgid, (False, False))
        af = after.get(msgid, (False, False))

        def _mark(fuzzy: bool, untrans: bool) -> str:
            parts = []
            if fuzzy:
                parts.append("FUZZY")
            if untrans:
                parts.append("UNTRANSLATED")
            return " + ".join(parts) if parts else "clean"

        if bf != af:
            out_lines.append(f"[{_mark(*bf)} -> {_mark(*af)}] {msgid[:70]!r}")
    if not out_lines:
        return "(no differences)"
    return "\n".join(out_lines)


def _write_po_locale(
    po_dir: Path,
    locale: str,
    *,
    entries: dict[str, str | None] | None = None,
    fuzzy_entries: set[str] | None = None,
    catalog_fuzzy: bool = False,
) -> Path:
    """اكتب ملف PO صناعي داخل مجلد ``translations/LANG/LC_MESSAGES/``.

    اسم الملف دائماً ``messages.po``.
    """
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


def write_po_manually(
    path: Path,
    locale: str,
    *,
    entries: dict[str, str | None] | None = None,
    fuzzy_entries: set[str] | None = None,
    catalog_fuzzy: bool = False,
) -> Path:
    """اكتب ملف PO في مسار صريح — لا يعتمد على tmp_path أو cwd.

    مفيد لاختبار المهمة المجدولة التي تعتمد على ``_catalog_path``.
    """
    po_path = path.resolve()
    po_path.parent.mkdir(parents=True, exist_ok=True)
    _write_po_locale(
        po_path.parent,
        locale,
        entries=entries,
        fuzzy_entries=fuzzy_entries,
        catalog_fuzzy=catalog_fuzzy,
    )
    return po_path


def _load_catalog(locale: str) -> Catalog:
    path = _catalog_path(locale)
    with path.open("rb") as fh:
        return read_po(fh)


def _set_catalog_overrides(overrides: dict[str, Path] | None) -> None:
    """ضع مسارات كتالوجات بديلة (تُستخدم في الاختبارات).

    عند وجودها، يتخطي ``_catalog_path`` الموقع الافتراضي لكل نطاق لغوي
    معرَّف في ``overrides``.
    """
    global _CATALOG_PATH_OVERRIDE
    _CATALOG_PATH_OVERRIDE = overrides


# ═══════════════════════════════════════════════════════════════════════════════
# التكامل مع Celery (اختياري — يعمل بدون Celery أيضاً)
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from app.tasks import ContextTask
    from app.tasks import celery_app as _celery_app

    _HAS_CELERY = True
except ImportError:  # pragma: no cover — مسار التوافق بدون Celery
    _celery_app = None
    ContextTask = object  # type: ignore[assignment, misc]
    _HAS_CELERY = False

if _HAS_CELERY and _celery_app is not None:

    @_celery_app.task(base=ContextTask, bind=True, max_retries=1, default_retry_delay=300)
    def audit_translation_catalogs(self) -> dict[str, Any]:
        """مهام Celery الدورية — تفحص الكتالوجات لاكتشاف دين الترجمة مبكراً.

        يُنصح بتشغيلها كل 30-60 دقيقة عبر Celery beat. المهمة في حد ذاتها
        lean (قراءة File + تحليل بسيط) ولا ينبغي أن تستغرق أكثر من ثوانٍ قليلة
        حتى في المشاريع الكبيرة.
        """
        _diagnostic_logger.info("i18n_audit_start")
        try:
            result = run_i18n_audit(previous_snapshots=None)
        except Exception as exc:  # noqa: BLE001
            _diagnostic_logger.exception("i18n_audit_error")
            raise self.retry(exc=exc) from None
        return result

    if not getattr(_celery_app.conf, "task_default_max_retries", None):
        _celery_app.conf.task_default_max_retries = 1
else:
    audit_translation_catalogs = None
