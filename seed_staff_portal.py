"""
Seed script for Staff Portal test data
Seeds runner pickups, deliveries, maintenance work orders, equipment issues, and notifications
"""
import asyncio
from datetime import datetime, timedelta
import random
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.db.session import async_session_maker
from app.models.staff import Staff
from app.models.inventory import Room
from app.models.runner import RunnerPickupRequest, RunnerDelivery, RunnerActivityLog
from app.models.maintenance import EquipmentIssues
from app.models.operations import MaintenanceRequest
from app.models.guest_chat import StaffNotification, StaffTask


async def seed_staff_portal():
    async with async_session_maker() as session:
        print("=" * 50)
        print("SEEDING STAFF PORTAL DATA")
        print("=" * 50)

        # Get existing staff members
        result = await session.exec(select(Staff))
        staff_list = result.all()

        if not staff_list:
            print("ERROR: No staff members found. Please run seed_comprehensive.py first.")
            return

        # Get rooms
        rooms_result = await session.exec(select(Room).limit(10))
        rooms = rooms_result.all()

        if not rooms:
            print("ERROR: No rooms found. Please run seed_comprehensive.py first.")
            return

        print(f"Found {len(staff_list)} staff members and {len(rooms)} rooms")

        # Find runners
        runners = [s for s in staff_list if s.department == 'runner' or s.role == 'runner']
        maintenance_staff = [s for s in staff_list if s.department == 'maintenance' or s.role == 'maintenance']
        housekeeping_staff = [s for s in staff_list if s.department == 'housekeeping' or s.role == 'housekeeping']

        if not runners:
            print("No runner staff found, using first staff member")
            runners = staff_list[:1]

        if not maintenance_staff:
            print("No maintenance staff found, using second staff member")
            maintenance_staff = staff_list[1:2] if len(staff_list) > 1 else staff_list[:1]

        print(f"Runners: {len(runners)}, Maintenance: {len(maintenance_staff)}, Housekeeping: {len(housekeeping_staff)}")

        # ============== SEED PICKUP REQUESTS ==============
        print("\n--- Seeding Pickup Requests ---")

        pickup_types = ['luggage', 'laundry', 'package', 'amenity_request', 'other']
        priorities = ['low', 'normal', 'high', 'urgent']
        statuses = ['pending', 'in_progress', 'completed']

        pickup_templates = [
            {"type": "luggage", "items": "2 suitcases, 1 carry-on", "dest": "Storage Room"},
            {"type": "laundry", "items": "Express laundry bag", "dest": "Laundry Room"},
            {"type": "package", "items": "Amazon package", "dest": "Guest Room"},
            {"type": "amenity_request", "items": "Extra towels and pillows", "dest": "Guest Room"},
            {"type": "luggage", "items": "Golf clubs and 1 suitcase", "dest": "Bell Desk"},
        ]

        for i in range(8):
            template = random.choice(pickup_templates)
            room = random.choice(rooms)
            status = random.choice(statuses)
            priority = random.choice(priorities)
            runner = random.choice(runners) if runners else None

            pickup = RunnerPickupRequest(
                request_number=f"PU-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                room_id=room.id,
                room_number=room.number,
                guest_name=f"Guest {random.randint(100, 999)}",
                pickup_type=template["type"],
                items_description=template["items"],
                item_count=random.randint(1, 5),
                pickup_location=f"Room {room.number}",
                destination=template["dest"],
                scheduled_time=datetime.utcnow() + timedelta(hours=random.randint(-2, 4)),
                priority=priority,
                status=status,
                requested_by="Front Desk",
                requested_at=datetime.utcnow() - timedelta(hours=random.randint(0, 8)),
                assigned_to=runner.id if runner and status != 'pending' else None,
                accepted_at=datetime.utcnow() - timedelta(minutes=random.randint(5, 30)) if status != 'pending' else None,
                completed_at=datetime.utcnow() - timedelta(minutes=random.randint(1, 15)) if status == 'completed' else None,
                duration_minutes=random.randint(5, 25) if status == 'completed' else None,
            )
            session.add(pickup)
            print(f"  Created pickup: {pickup.request_number} - {pickup.pickup_type} - {pickup.status}")

        # ============== SEED DELIVERIES ==============
        print("\n--- Seeding Deliveries ---")

        delivery_types = ['room_service', 'package', 'laundry', 'amenity', 'other']
        delivery_statuses = ['pending', 'in_transit', 'delivered']

        delivery_templates = [
            {"type": "room_service", "items": "Breakfast order - eggs, toast, coffee", "origin": "Kitchen"},
            {"type": "package", "items": "FedEx delivery", "origin": "Mail Room"},
            {"type": "laundry", "items": "Pressed shirts and dry cleaning", "origin": "Laundry"},
            {"type": "amenity", "items": "Extra blankets and pillows", "origin": "Housekeeping"},
            {"type": "room_service", "items": "In-room dining - pasta and wine", "origin": "Kitchen"},
        ]

        for i in range(8):
            template = random.choice(delivery_templates)
            room = random.choice(rooms)
            status = random.choice(delivery_statuses)
            priority = random.choice(priorities)
            runner = random.choice(runners) if runners else None

            delivery = RunnerDelivery(
                delivery_number=f"DL-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                delivery_type=template["type"],
                room_id=room.id,
                room_number=room.number,
                guest_name=f"Guest {random.randint(100, 999)}",
                items_description=template["items"],
                item_count=random.randint(1, 4),
                origin_location=template["origin"],
                destination_location=f"Room {room.number}",
                priority=priority,
                status=status,
                ordered_at=datetime.utcnow() - timedelta(hours=random.randint(0, 4)),
                assigned_to=runner.id if runner and status != 'pending' else None,
                accepted_at=datetime.utcnow() - timedelta(minutes=random.randint(5, 20)) if status != 'pending' else None,
                picked_up_at=datetime.utcnow() - timedelta(minutes=random.randint(3, 15)) if status in ['in_transit', 'delivered'] else None,
                delivered_at=datetime.utcnow() - timedelta(minutes=random.randint(1, 10)) if status == 'delivered' else None,
                estimated_delivery_time=datetime.utcnow() + timedelta(minutes=random.randint(10, 30)),
                duration_minutes=random.randint(8, 20) if status == 'delivered' else None,
                temperature_sensitive=template["type"] == "room_service",
                fragile=False,
            )
            session.add(delivery)
            print(f"  Created delivery: {delivery.delivery_number} - {delivery.delivery_type} - {delivery.status}")

        # ============== SEED MAINTENANCE WORK ORDERS ==============
        print("\n--- Seeding Maintenance Work Orders ---")

        issue_types = ['plumbing', 'electrical', 'hvac', 'structural', 'appliance', 'other']
        wo_statuses = ['pending', 'in_progress', 'completed']

        work_order_templates = [
            {"title": "Leaky faucet in bathroom", "type": "plumbing", "priority": "medium"},
            {"title": "AC not cooling properly", "type": "hvac", "priority": "high"},
            {"title": "Light fixture flickering", "type": "electrical", "priority": "low"},
            {"title": "TV remote not working", "type": "appliance", "priority": "low"},
            {"title": "Door lock needs adjustment", "type": "structural", "priority": "medium"},
            {"title": "Mini fridge not cooling", "type": "appliance", "priority": "high"},
            {"title": "Shower drain slow", "type": "plumbing", "priority": "medium"},
        ]

        for i, template in enumerate(work_order_templates):
            room = random.choice(rooms)
            status = random.choice(wo_statuses)
            maint = random.choice(maintenance_staff) if maintenance_staff else None

            work_order = MaintenanceRequest(
                title=template["title"],
                description=f"Guest reported: {template['title'].lower()}. Please investigate and repair.",
                location=f"Room {room.number}",
                room_id=room.id,
                room_number=room.number,
                issue_type=template["type"],
                priority=template["priority"],
                status=status,
                reported_by=maint.id if maint else None,
                reported_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
                assigned_to=maint.id if maint and status != 'pending' else None,
                completed_at=datetime.utcnow() - timedelta(hours=random.randint(0, 4)) if status == 'completed' else None,
                resolution_notes="Issue resolved" if status == 'completed' else None,
            )
            session.add(work_order)
            print(f"  Created work order: {template['title']} - {status}")

        # ============== SEED EQUIPMENT ISSUES ==============
        print("\n--- Seeding Equipment Issues ---")

        equipment_templates = [
            {"name": "Pool Heater", "category": "pool", "issue": "Temperature fluctuating", "severity": "medium"},
            {"name": "Elevator #2", "category": "elevator", "issue": "Unusual noise during operation", "severity": "high"},
            {"name": "Kitchen Refrigerator", "category": "kitchen", "issue": "Ice maker malfunction", "severity": "medium"},
            {"name": "Generator", "category": "generator", "issue": "Scheduled maintenance due", "severity": "low"},
            {"name": "Fire Alarm Panel", "category": "safety", "issue": "Sensor calibration needed", "severity": "critical"},
        ]

        equipment_statuses = ['pending', 'in_progress', 'resolved']
        reporter = maintenance_staff[0] if maintenance_staff else staff_list[0]

        for i, template in enumerate(equipment_templates):
            status = random.choice(equipment_statuses)
            maint = random.choice(maintenance_staff) if maintenance_staff else None

            issue = EquipmentIssues(
                issue_number=f"EQ-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                equipment_name=template["name"],
                equipment_category=template["category"],
                location="Main Building",
                issue_type="Malfunction",
                issue_description=template["issue"],
                severity=template["severity"],
                status=status,
                reported_by=reporter.id,
                reported_at=datetime.utcnow() - timedelta(days=random.randint(0, 7)),
                assigned_to=maint.id if maint and status != 'pending' else None,
                accepted_at=datetime.utcnow() - timedelta(hours=random.randint(1, 24)) if status != 'pending' else None,
                resolved_at=datetime.utcnow() - timedelta(hours=random.randint(0, 12)) if status == 'resolved' else None,
                resolution_notes="Equipment repaired and tested" if status == 'resolved' else None,
                affects_operations=template["severity"] in ['high', 'critical'],
            )
            session.add(issue)
            print(f"  Created equipment issue: {template['name']} - {template['severity']} - {status}")

        # ============== SEED NOTIFICATIONS ==============
        print("\n--- Seeding Staff Notifications ---")

        # Get existing tasks to link notifications to
        tasks_result = await session.exec(select(StaffTask).limit(5))
        existing_tasks = tasks_result.all()

        if existing_tasks:
            notification_templates = [
                {"type": "task_assigned", "title": "New Task Assigned", "msg": "You have been assigned a new housekeeping task for Room {room}."},
                {"type": "task_reminder", "title": "Task Reminder", "msg": "Task for Room {room} is due in 30 minutes."},
                {"type": "task_update", "title": "Task Updated", "msg": "Task for Room {room} has been updated."},
            ]

            # Create notifications linked to existing tasks
            for staff in staff_list[:5]:  # Limit to first 5 staff
                for task in existing_tasks[:3]:  # 3 notifications each, linked to tasks
                    template = random.choice(notification_templates)
                    room = random.choice(rooms)

                    notification = StaffNotification(
                        staff_id=staff.user_id if staff.user_id else staff.id,
                        task_id=task.id,
                        notification_type=template["type"],
                        title=template["title"],
                        message=template["msg"].format(room=room.number),
                        is_read=random.choice([True, False, False]),  # 66% unread
                        read_at=datetime.utcnow() - timedelta(hours=random.randint(0, 12)) if random.random() > 0.66 else None,
                        created_at=datetime.utcnow() - timedelta(hours=random.randint(0, 48)),
                    )
                    session.add(notification)
                print(f"  Created notifications for {staff.name}")
        else:
            print("  Skipping notifications - no existing tasks found to link to")
            print("  (Notifications require a task_id - run housekeeping seeder first)")

        await session.commit()

        print("\n" + "=" * 50)
        print("STAFF PORTAL DATA SEEDED SUCCESSFULLY!")
        print("=" * 50)
        print("\nSummary:")
        print("  - 8 Pickup Requests")
        print("  - 8 Deliveries")
        print("  - 7 Work Orders")
        print("  - 5 Equipment Issues")
        print("  - 15 Notifications")
        print("\nYou can now test the staff portal with real data!")


if __name__ == "__main__":
    asyncio.run(seed_staff_portal())
