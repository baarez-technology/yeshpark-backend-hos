"""Script to fix action_intents set in admin_ai_assistant.py"""

# Read the current file
with open('app/services/admin_ai_assistant.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_text = '''            action_intents = {
                AdminIntent.ASSIGN_ROOM, AdminIntent.TRANSFER_ROOM, AdminIntent.CREATE_GUEST_NOTE,
                AdminIntent.CREATE_BOOKING, AdminIntent.UPDATE_BOOKING, AdminIntent.CANCEL_BOOKING,
                AdminIntent.ASSIGN_TASK, AdminIntent.UPDATE_ROOM, AdminIntent.SEND_EMAIL,
                AdminIntent.SEND_NOTIFICATION, AdminIntent.FOLLOW_UP, AdminIntent.CONFIRM_ACTION,
                AdminIntent.CANCEL_ACTION, AdminIntent.CHECK_IN, AdminIntent.CHECK_OUT,
            }'''

new_text = '''            action_intents = {
                AdminIntent.ASSIGN_ROOM, AdminIntent.TRANSFER_ROOM, AdminIntent.CREATE_GUEST_NOTE,
                AdminIntent.CREATE_BOOKING, AdminIntent.UPDATE_BOOKING, AdminIntent.ASSIGN_TASK,
                AdminIntent.UPDATE_ROOM, AdminIntent.SEND_EMAIL, AdminIntent.CREATE_TASK,
                AdminIntent.CREATE_MAINTENANCE, AdminIntent.FOLLOW_UP,
            }'''

if old_text not in content:
    print('ERROR: Pattern not found!')
    exit(1)

new_content = content.replace(old_text, new_text)

with open('app/services/admin_ai_assistant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: action_intents fixed!')
