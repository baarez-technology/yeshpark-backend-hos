import re

# Read the file
with open('E:/Glimmora_Updated/Backend/app/services/admin_ai/action_executor.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''    async def _create_maintenance_request(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Create a maintenance request"""
        params = action.params

        query = text("""
            INSERT INTO maintenancerequest
            (room_id, category, issue, description, priority, status, reported_by, created_at)
            VALUES (:room_id, :category, :issue, :description, :priority, 'open', :reported_by, :created_at)
        """)

        await self.session.execute(query, {
            "room_id": params.get("room_id"),
            "category": params.get("category", "general"),
            "issue": params.get("issue", "Maintenance required"),
            "description": params.get("description", "Created by Admin AI"),
            "priority": params.get("priority", "medium"),
            "reported_by": user_id,
            "created_at": datetime.utcnow().isoformat(),
        })
        await self.session.commit()'''

new_code = '''    async def _create_maintenance_request(
        self, action: ActionRequest, user_id: int, action_id: str
    ) -> ActionResult:
        """Create a maintenance request"""
        params = action.params

        # Generate work_order_id in format WO-YYYYMMDD-XXXX
        now = datetime.utcnow()
        date_str = now.strftime("%Y%m%d")

        # Get the next sequence number for today
        count_query = text("""
            SELECT COUNT(*) FROM maintenancerequest
            WHERE work_order_id LIKE :pattern
        """)
        result = await self.session.execute(count_query, {"pattern": f"WO-{date_str}-%"})
        count = result.scalar() or 0
        work_order_id = f"WO-{date_str}-{count:04d}"

        query = text("""
            INSERT INTO maintenancerequest
            (work_order_id, room_id, category, issue, description, priority, status, reported_by, reported_at)
            VALUES (:work_order_id, :room_id, :category, :issue, :description, :priority, 'open', :reported_by, :reported_at)
        """)

        await self.session.execute(query, {
            "work_order_id": work_order_id,
            "room_id": params.get("room_id"),
            "category": params.get("category", "general"),
            "issue": params.get("issue", "Maintenance required"),
            "description": params.get("description", "Created by Admin AI"),
            "priority": params.get("priority", "medium"),
            "reported_by": user_id,
            "reported_at": now.isoformat(),
        })
        await self.session.commit()'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('E:/Glimmora_Updated/Backend/app/services/admin_ai/action_executor.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully updated action_executor.py")
else:
    print("Old code not found - may already be updated")
