"""بوابة i18n لـCI — تفشل عند وجود سلاسل غير مترجمة أو fuzzy.

القواعد:
- en: أي msgstr فارغ أو علم fuzzy (إدخال أو رأس كتالوج) = فشل (exit 1).
- ar: لغة المصدر، فالـmsgstr الفارغ مقصود؛ فقط علم fuzzy = فشل.

Usage:
    python scripts/dump_untranslated.py [po_files ...]
"""

import sys
from pathlib import Path

from babel.messages.pofile import read_po

# ar لغة المصدر — msgstr الفارغ فيها هو التصميم المقصود، لا يُعتبر نقصاً.
SOURCE_LOCALES = {"ar"}
DEFAULT_CATALOGS = (
    Path("app/translations/en/LC_MESSAGES/messages.po"),
    Path("app/translations/ar/LC_MESSAGES/messages.po"),
)


def check(path: Path) -> list[str]:
    """يفحص كتالوجاً واحداً ويعيد قائمة أسباب الفشل."""
    with path.open("rb") as f:
        cat = read_po(f)

    locale = str(cat.locale) if cat.locale else path.parts[-4]
    issues: list[str] = []

    if cat.fuzzy:
        # رأس الكتالوج fuzzy يجعل pybabel compile يتخطاه بالكامل.
        issues.append(f"{path}: catalog header is marked fuzzy")

    for msg in cat:
        if not msg.id or getattr(msg, "obsolete", False):
            continue
        if "fuzzy" in msg.flags:
            issues.append(f"{path}: fuzzy entry: {msg.id[:60]!r}")
        elif not msg.string and locale not in SOURCE_LOCALES:
            issues.append(f"{path}: untranslated entry: {msg.id[:60]!r}")
    return issues


def main() -> int:
    catalogs = [Path(p) for p in sys.argv[1:]] or list(DEFAULT_CATALOGS)
    issues: list[str] = []
    for path in catalogs:
        if not path.exists():
            issues.append(f"{path}: file not found")
            continue
        issues.extend(check(path))

    if issues:
        print(f"❌ i18n check FAILED — {len(issues)} issue(s):")
        for issue in issues[:20]:
            print(f"  - {issue}")
        if len(issues) > 20:
            print(f"  ... and {len(issues) - 20} more")
        return 1

    print(f"✅ i18n check passed — {len(catalogs)} catalog(s), no untranslated or fuzzy entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
