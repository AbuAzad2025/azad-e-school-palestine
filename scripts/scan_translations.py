import re
from pathlib import Path
from collections import defaultdict

arabic_pattern = re.compile(r'[\u0600-\u06FF]+')

results = []
for html in Path('app/templates').rglob('*.html'):
    content = html.read_text(encoding='utf-8')
    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('{#') or stripped.startswith('<!--'):
            continue
        if '<style>' in line or '<script>' in line:
            continue

        arabic_matches = arabic_pattern.findall(line)
        if arabic_matches:
            for match in arabic_matches:
                match_pos = line.find(match)
                before = line[:match_pos]
                if '_( ' in before[-10:] or '_("' in before[-10:] or "_('" in before[-10:]:
                    continue
                results.append((str(html), i, match, line.strip()[:120]))

by_file = defaultdict(list)
for f, l, t, ctx in results:
    by_file[f].append((l, t, ctx))

output = []
for f in sorted(by_file.keys()):
    output.append(f'\n=== {f} ===')
    for l, t, ctx in by_file[f]:
        output.append(f'  L{l}: "{t}"  ->  {ctx}')

Path('scripts/translation_results.txt').write_text('\n'.join(output), encoding='utf-8')
print(f"Done. Found {len(results)} hardcoded Arabic strings in {len(by_file)} files.")