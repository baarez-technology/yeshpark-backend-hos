"""Script to fix CREATE_GUEST_NOTE pattern priority over VIP patterns"""

# Read the current file
with open('app/services/admin_ai_assistant.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The current VIP patterns start
old_vip_section = '''        # === VIP GUESTS ===
        (r"(vip|platinum|gold|loyal|special).*(guest|customer|member)", AdminIntent.QUERY_VIP_GUESTS),
        (r"(top|best|high.?value|premium|valued).*(guest|customer)", AdminIntent.QUERY_VIP_GUESTS),
        (r"(show|list|who).*(vip|special|important)", AdminIntent.QUERY_VIP_GUESTS),
        (r"our.*(best|top|vip).*(guest|customer)", AdminIntent.QUERY_VIP_GUESTS),'''

# Add action-specific patterns BEFORE VIP patterns
new_vip_section = '''        # === ACTION INTENTS (check before query intents) ===
        # CREATE GUEST NOTE - must come before VIP to avoid "VIP" in note content triggering VIP query
        (r"(add|create|write|make)\s+(a\s+)?(note|comment|remark)\s+(for|to|about|on)", AdminIntent.CREATE_GUEST_NOTE),
        (r"(note|comment)\s+.*:\s+", AdminIntent.CREATE_GUEST_NOTE),  # "note to guest 1: content"

        # === VIP GUESTS ===
        (r"(vip|platinum|gold|loyal|special).*(guest|customer|member)", AdminIntent.QUERY_VIP_GUESTS),
        (r"(top|best|high.?value|premium|valued).*(guest|customer)", AdminIntent.QUERY_VIP_GUESTS),
        (r"(show|list|who).*(vip|special|important)", AdminIntent.QUERY_VIP_GUESTS),
        (r"our.*(best|top|vip).*(guest|customer)", AdminIntent.QUERY_VIP_GUESTS),'''

if old_vip_section not in content:
    print('ERROR: VIP section pattern not found!')
    exit(1)

new_content = content.replace(old_vip_section, new_vip_section)

with open('app/services/admin_ai_assistant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: CREATE_GUEST_NOTE patterns added before VIP patterns!')
