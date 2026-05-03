import re

with open('tests/test_workbook.py', 'r') as f:
    content = f.read()

# Fix all wb = Workbook() patterns to remove default sheet
content = re.sub(
    r'(wb = Workbook\(\)\n    )(main|ws) = wb\.create_sheet',
    r'\1# Remove default sheet, create proper structure\n    wb.remove(wb.active)\n    wb.create_sheet("Cover")\n    wb.create_sheet("Revisions")\n    \2 = wb.create_sheet',
    content
)

with open('tests/test_workbook.py', 'w') as f:
    f.write(content)

print('Fixed')