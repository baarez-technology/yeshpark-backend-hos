"""Fix: Make pending actions persist across requests using module-level cache"""

# Read the current file
with open('app/services/admin_ai/action_executor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add module-level pending actions cache after imports
old_imports_end = '''from app.models.room import Room
from app.models.user import User'''

new_imports = '''from app.models.room import Room
from app.models.user import User

# Module-level pending actions cache (persists across requests)
_GLOBAL_PENDING_ACTIONS: Dict[str, "PendingAction"] = {}'''

if old_imports_end not in content:
    print('ERROR: Import pattern not found!')
    exit(1)

content = content.replace(old_imports_end, new_imports)

# Modify __init__ to use global cache
old_init = '''        self._pending_actions: Dict[str, PendingAction] = {}'''
new_init = '''        # Use global cache for pending actions (persists across requests)
        global _GLOBAL_PENDING_ACTIONS
        self._pending_actions = _GLOBAL_PENDING_ACTIONS'''

if old_init not in content:
    print('ERROR: __init__ pattern not found!')
    exit(1)

content = content.replace(old_init, new_init)

with open('app/services/admin_ai/action_executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('SUCCESS: Pending actions now persist across requests!')
