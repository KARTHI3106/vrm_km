import re

file_path = r'd:\vrm\backend\app\api\routes.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix double-escaped newlines in the prompt template
content = content.replace(
    r'template="Extract vendor onboarding details from the following command.\\n{format_instructions}\\n\\nCommand:\\n{prompt}\\n"',
    'template="Extract vendor onboarding details from the following command.\\n{format_instructions}\\n\\nCommand:\\n{prompt}\\n"'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
