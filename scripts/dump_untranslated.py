"""أداة صيانة: استخراج السلاسل غير المترجمة من كتالوج en إلى ملف نصي.

Usage: .venv/Scripts/python.exe scripts/dump_untranslated.py
"""

import sys

from babel.messages.pofile import read_po

PO = "app/translations/en/LC_MESSAGES/messages.po"
OUT = "need_en_tmp.txt"

with open(PO, "rb") as f:
    cat = read_po(f)

need = [m.id for m in cat if isinstance(m.id, str) and (not m.string or "fuzzy" in m.flags)]
with open(OUT, "w", encoding="utf-8") as out:
    for s in need:
        out.write(s + "\n=====\n")
print(len(need), sys.stderr and "")
