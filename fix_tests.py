import re

# Fix test_content_reuse.py
with open('tests/test_content_reuse.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace byte assertions with string assertions - more careful approach
# Find lines with b"arabic" and replace
lines = content.split('\n')
new_lines = []
for line in lines:
    # Replace b"arabic text" in resp.data with "arabic text" in data
    if 'b"' in line and 'resp.data' in line:
        # Replace b"..." with "..." and resp.data with data
        line = line.replace('b"', '"').replace('resp.data', 'data')
        # Add data = resp.get_data(as_text=True) before if not already there
        if 'data = resp.get_data(as_text=True)' not in '\n'.join(new_lines[-5:]):
            # Check if previous lines have the data variable
            indent = len(line) - len(line.lstrip())
            new_lines.append(' ' * indent + 'data = resp.get_data(as_text=True)')
    new_lines.append(line)

content = '\n'.join(new_lines)

with open('tests/test_content_reuse.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed test_content_reuse.py')