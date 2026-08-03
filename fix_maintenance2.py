# Read the file
with open('E:/Glimmora_Updated/Backend/app/services/admin_ai/action_executor.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''        query = text("""
            INSERT INTO maintenancerequest
            (work_order_id, room_id, category, issue, description, priority, status, reported_by, reported_at)
            VALUES (:work_order_id, :room_id, :category, :issue, :description, :priority, 'open', :reported_by, :reported_at)
        """)'''

new_code = '''        query = text("""
            INSERT INTO maintenancerequest
            (work_order_id, room_id, category, issue, description, priority, status, reported_by, reported_at, is_out_of_order, requires_parts, parts_ordered, is_preventive)
            VALUES (:work_order_id, :room_id, :category, :issue, :description, :priority, 'open', :reported_by, :reported_at, 0, 0, 0, 0)
        """)'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('E:/Glimmora_Updated/Backend/app/services/admin_ai/action_executor.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully updated action_executor.py")
else:
    print("Old code not found - may already be updated")
