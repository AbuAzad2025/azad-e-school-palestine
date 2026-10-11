import re
from pathlib import Path
from collections import defaultdict

arabic_pattern = re.compile(r'[\u0600-\u06FF]+')

results = []
for html in Path('app/templates').rglob('*.html'):
    content = html.read_text(encoding='utf-8')
    
    # First, find all _() translations and mark their ranges
    translation_ranges = []
    for m in re.finditer(r'_\s*\(\s*["\']([^"\']*[\u0600-\u06FF]+[^"\']*)["\']\s*\)', content):
        translation_ranges.append((m.start(), m.end()))
    
    # Also {% trans %} blocks
    for m in re.finditer(r'{%\s*trans\s*%}.*?{%\s*endtrans\s*%}', content, re.DOTALL):
        translation_ranges.append((m.start(), m.end()))
    
    # Also {{ _() }} calls
    for m in re.finditer(r'\{\{\s*_\s*\([^}]*\}\)\s*\}\}', content):
        translation_ranges.append((m.start(), m.end()))

    lines = content.split('\n')
    char_pos = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('{#') or stripped.startswith('<!--'):
            char_pos += len(line) + 1
            continue
        if '<style>' in line or '<script>' in line:
            char_pos += len(line) + 1
            continue

        line_start = char_pos
        line_end = char_pos + len(line)

        arabic_matches = list(arabic_pattern.finditer(line))
        if arabic_matches:
            for m in arabic_matches:
                match_pos = line_start + m.start()
                match_end = line_start + m.end()
                
                # Check if this match is inside any translation range
                inside_translation = False
                for tr_start, tr_end in translation_ranges:
                    if tr_start <= match_pos and match_end <= tr_end:
                        inside_translation = True
                        break
                
                if not inside_translation:
                    results.append((str(html), i, m.group(), line.strip()[:150]))

        char_pos += len(line) + 1

by_file = defaultdict(list)
for f, l, t, ctx in results:
    by_file[f].append((l, t, ctx))

output = []
for f in sorted(by_file.keys()):
    output.append(f'\n=== {f} ===')
    for l, t, ctx in by_file[f]:
        output.append(f'  L{l}: "{t}"  ->  {ctx}')

Path('scripts/translation_results.txt').write_text('\n'.join(output), encoding='utf-8')
print(f"Done. Found {len(results)} UNTRANSLATED Arabic strings in {len(by_file)} files.")