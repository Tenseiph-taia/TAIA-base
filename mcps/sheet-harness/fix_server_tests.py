import re

with open('tests/test_server.py', 'r') as f:
    content = f.read()

# Fix all wb = Workbook() patterns to remove default sheet
content = re.sub(
    r'(wb = Workbook\(\)\n    )(ws|wb2) = wb\.create_sheet',
    r'\1# Remove default sheet, create proper structure\n    wb.remove(wb.active)\n    wb.create_sheet("Cover")\n    wb.create_sheet("Revisions")\n    \2 = wb.create_sheet',
    content
)

# Also fix patterns where next line is for c in range
content = re.sub(
    r'(wb = Workbook\(\)\n    )for c in range',
    r'\1# Remove default sheet, create proper structure\n    wb.remove(wb.active)\n    wb.create_sheet("Cover")\n    wb.create_sheet("Revisions")\n    ws = wb.create_sheet("Main")\n    for c in range',
    content
)

with open('tests/test_server.py', 'w') as f:
    f.write(content)

print('Fixed server tests')