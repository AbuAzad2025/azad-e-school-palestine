import re

def fix_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    new_lines = []
    for i, line in enumerate(lines):
        # Replace b"arabic text" in resp.data with "arabic text" in data
        if 'b"' in line and 'resp.data' in line:
            line = line.replace('b"', '"').replace('resp.data', 'data')
            # Add data = resp.get_data(as_text=True) before if not already there
            if 'data = resp.get_data(as_text=True)' not in '\n'.join(new_lines[-5:]):
                indent = len(line) - len(line.lstrip())
                new_lines.append(' ' * indent + 'data = resp.get_data(as_text=True)')
        new_lines.append(line)

    content = '\n'.join(new_lines)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'Fixed {filename}')

fix_file('tests/test_quiz_stats.py')
fix_file('tests/test_tutor_ratings.py')