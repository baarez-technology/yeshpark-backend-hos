"""
Clean Staff Seed Script
Creates exactly 3 staff members for the staff portal demo:
- Maria Rodriguez (Housekeeping)
- John Smith (Maintenance)
- Alex Johnson (Runner)

Also creates proper operational data following hotel workflow logic.
"""
import asyncio
import json
from datetime import datetime, timedelta, date, time
import random
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete

from app.db.session import async_session_maker, init_db
from app.core.security import get_password_hash
from app.models.user import User
from app.models.staff import Staff, StaffSchedule, StaffAttendance
from app.models.inventory import Room
from app.models.operations import HousekeepingTask, MaintenanceRequest
from app.models.runner import RunnerPickupRequest, RunnerDelivery
from app.models.maintenance import EquipmentIssues
from app.models.guest_chat import StaffNotification, StaffTask


async def seed_clean_staff():
    """Create clean staff data with proper workflow logic"""
    await init_db()

    async with async_session_maker() as session:
        print("=" * 60)
        print("CLEANING AND SEEDING STAFF DATA")
        print("=" * 60)

        # ========== STEP 1: Clean up existing data ==========
        print("\n[1/6] Cleaning up existing operational and staff data...")

        # Delete notifications
        await session.exec(delete(StaffNotification))
        # Delete runner data
        await session.exec(delete(RunnerPickupRequest))
        await session.exec(delete(RunnerDelivery))
        # Delete maintenance data
        await session.exec(delete(EquipmentIssues))
        await session.exec(delete(MaintenanceRequest))
        # Delete housekeeping tasks
        await session.exec(delete(HousekeepingTask))
        # Delete staff tasks
        await session.exec(delete(StaffTask))

        await session.commit()

        # Delete ALL existing staff records (we'll recreate only the 3 we need)
        await session.exec(delete(StaffSchedule))
        await session.exec(delete(StaffAttendance))
        await session.exec(delete(Staff))
        await session.commit()

        print("  [OK] Cleaned up existing operational and staff data")

        # ========== STEP 2: Get or create the 3 main staff accounts ==========
        print("\n[2/6] Setting up 3 staff accounts...")

        staff_configs = [
            {
                "email": "maria@glimmora.local",
                "name": "Maria Rodriguez",
                "password": "123456",
                "role": "housekeeping",
                "department": "housekeeping",
                "employee_id": "HK-001",
                "specialty": "Deep Cleaning & Suite Preparation",
                "shift": "morning",
                "shift_start": time(7, 0),
                "shift_end": time(15, 0),
                "floor_assignment": "5,6,7,8",
                "phone": "+1 (555) 100-0008",
                "performance_rating": 4.8,
                "hourly_rate": 18.0,
                "skills": ["Deep Cleaning", "Suite Preparation", "Turndown Service", "Laundry"],
                "languages": ["English", "Spanish"],
            },
            {
                "email": "john@glimmora.local",
                "name": "John Smith",
                "password": "123456",
                "role": "maintenance",
                "department": "maintenance",
                "employee_id": "MT-001",
                "specialty": "HVAC & Electrical Systems",
                "shift": "morning",
                "shift_start": time(7, 0),
                "shift_end": time(15, 0),
                "floor_assignment": None,
                "phone": "+1 (555) 100-0009",
                "performance_rating": 4.7,
                "hourly_rate": 28.0,
                "skills": ["HVAC", "Electrical", "Plumbing", "General Repairs"],
                "languages": ["English"],
            },
            {
                "email": "alex@glimmora.local",
                "name": "Alex Johnson",
                "password": "123456",
                "role": "runner",
                "department": "runner",
                "employee_id": "RN-001",
                "specialty": "Guest Services & Deliveries",
                "shift": "morning",
                "shift_start": time(7, 0),
                "shift_end": time(15, 0),
                "floor_assignment": None,
                "phone": "+1 (555) 100-0010",
                "performance_rating": 4.6,
                "hourly_rate": 16.0,
                "skills": ["Guest Relations", "Package Handling", "Room Service"],
                "languages": ["English", "French"],
            },
        ]

        staff_objects = {}

        for config in staff_configs:
            # Check if user exists
            result = await session.exec(select(User).where(User.email == config["email"]))
            user = result.first()

            if not user:
                # Create user
                user = User(
                    email=config["email"],
                    full_name=config["name"],
                    hashed_password=get_password_hash(config["password"]),
                    is_active=True,
                    role=config["role"],
                    phone=config["phone"],
                )
                session.add(user)
                await session.flush()
                print(f"  [OK] Created user: {config['name']}")
            else:
                # Update user role to match
                user.role = config["role"]
                user.full_name = config["name"]
                print(f"  [EXISTS] User exists: {config['name']}")

            # Check if staff record exists
            result = await session.exec(select(Staff).where(Staff.user_id == user.id))
            staff = result.first()

            if not staff:
                staff = Staff(
                    user_id=user.id,
                    employee_id=config["employee_id"],
                    name=config["name"],
                    email=config["email"],
                    phone=config["phone"],
                    role=config["role"],
                    department=config["department"],
                    specialty=config["specialty"],
                    status="active",
                    shift=config["shift"],
                    shift_start=config["shift_start"],
                    shift_end=config["shift_end"],
                    floor_assignment=config["floor_assignment"],
                    performance_rating=config["performance_rating"],
                    hourly_rate=config["hourly_rate"],
                    hire_date=date.today() - timedelta(days=365),
                    clocked_in=True,  # Start clocked in for demo
                    clock_in_time=datetime.now().replace(hour=7, minute=0, second=0),
                    skills=json.dumps(config["skills"]),
                    languages_spoken=json.dumps(config["languages"]),
                )
                session.add(staff)
                await session.flush()
                print(f"  [OK] Created staff record: {config['name']} ({config['department']})")
            else:
                # Update existing staff record
                staff.name = config["name"]
                staff.role = config["role"]
                staff.department = config["department"]
                staff.employee_id = config["employee_id"]
                staff.specialty = config["specialty"]
                staff.shift = config["shift"]
                staff.shift_start = config["shift_start"]
                staff.shift_end = config["shift_end"]
                staff.floor_assignment = config["floor_assignment"]
                staff.skills = json.dumps(config["skills"])
                staff.languages_spoken = json.dumps(config["languages"])
                staff.clocked_in = True
                staff.clock_in_time = datetime.now().replace(hour=7, minute=0, second=0)
                print(f"  [UPDATED] Updated staff: {config['name']}")

            staff_objects[config["department"]] = staff

        await session.commit()

        # ========== STEP 3: Get rooms for task assignment ==========
        print("\n[3/6] Loading rooms...")

        result = await session.exec(select(Room).limit(50))
        rooms = result.all()

        if not rooms:
            print("  [ERROR] No rooms found! Please run seed_comprehensive.py first.")
            return

        print(f"  [OK] Found {len(rooms)} rooms")

        # Organize rooms by floor
        floors_5_8 = [r for r in rooms if r.floor in [5, 6, 7, 8]]

        # ========== STEP 4: Create Housekeeping Tasks ==========
        print("\n[4/6] Creating housekeeping tasks for Maria...")

        maria = staff_objects["housekeeping"]
        task_count = 0

        # HOUSEKEEPING WORKFLOW:
        # Room Status: dirty -> cleaning (in_progress) -> needs_inspection -> clean
        # Task Status: pending -> in_progress -> done

        task_templates = [
            {"type": "cleaning", "priority": "high", "notes": "Checkout clean - Guest departed this morning"},
            {"type": "cleaning", "priority": "normal", "notes": "Stay-over clean - Guest extending stay"},
            {"type": "deep_clean", "priority": "low", "notes": "Scheduled deep cleaning"},
            {"type": "turndown", "priority": "normal", "notes": "Evening turndown service"},
            {"type": "inspection", "priority": "high", "notes": "Quality check before VIP arrival"},
        ]

        # Create mix of tasks in different statuses
        for i, room in enumerate(floors_5_8[:12]):
            template = task_templates[i % len(task_templates)]

            # Determine status based on index for variety
            if i < 3:
                status = "pending"
                room_status = "dirty"
            elif i < 6:
                status = "in_progress"
                room_status = "dirty"  # Being cleaned
            elif i < 9:
                status = "completed"
                room_status = "inspected"
            else:
                status = "pending"
                room_status = "dirty"

            # Update room status
            room.status = room_status

            task = HousekeepingTask(
                room_id=room.id,
                task_type=template["type"],
                status=status,
                priority=template["priority"],
                assigned_to=maria.id,
                scheduled_for=datetime.now() + timedelta(hours=i),
                estimated_duration=45 if template["type"] == "cleaning" else 30,
                notes=template["notes"],
                started_at=datetime.now() - timedelta(minutes=30) if status == "in_progress" else None,
                completed_at=datetime.now() - timedelta(minutes=10) if status == "completed" else None,
            )
            session.add(task)
            task_count += 1

        await session.commit()
        print(f"  [OK] Created {task_count} housekeeping tasks")

        # ========== STEP 5: Create Maintenance Work Orders ==========
        print("\n[5/6] Creating maintenance work orders and equipment issues for John...")

        john = staff_objects["maintenance"]

        # MAINTENANCE WORKFLOW:
        # Work Order: open -> assigned -> in_progress -> completed
        # Equipment Issue: pending -> in_progress -> resolved

        work_order_templates = [
            {"issue": "AC Unit Not Cooling", "category": "hvac", "priority": "high", "room": True},
            {"issue": "Bathroom Faucet Leaking", "category": "plumbing", "priority": "medium", "room": True},
            {"issue": "Light Fixture Flickering", "category": "electrical", "priority": "low", "room": True},
            {"issue": "TV Not Working", "category": "appliance", "priority": "medium", "room": True},
            {"issue": "Door Lock Malfunction", "category": "general", "priority": "high", "room": True},
            {"issue": "Elevator #2 Maintenance", "category": "general", "priority": "high", "room": False},
            {"issue": "Pool Heater Inspection", "category": "hvac", "priority": "medium", "room": False},
        ]

        wo_count = 0
        statuses = ["open", "assigned", "in_progress", "completed"]

        for i, template in enumerate(work_order_templates):
            status = statuses[i % len(statuses)]
            room = rooms[i] if template["room"] else None

            wo = MaintenanceRequest(
                work_order_id=f"WO-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                issue=template["issue"],
                category=template["category"],
                description=f"Reported issue: {template['issue']}. Please investigate and repair.",
                location=f"Room {room.number}" if room else "Common Area",
                room_id=room.id if room else None,
                priority=template["priority"],
                status=status,
                reported_by=john.id,
                reported_at=datetime.now() - timedelta(hours=i * 2),
                assigned_to=john.id if status != "open" else None,
                started_at=datetime.now() - timedelta(hours=1) if status == "in_progress" else None,
                completed_at=datetime.now() - timedelta(minutes=30) if status == "completed" else None,
                resolution_notes="Issue resolved and tested" if status == "completed" else None,
            )
            session.add(wo)
            wo_count += 1

        # Equipment Issues
        equipment_templates = [
            {"name": "Pool Heater Unit #1", "category": "pool", "issue": "Temperature inconsistent", "severity": "medium"},
            {"name": "Elevator #2", "category": "elevator", "issue": "Unusual noise during operation", "severity": "high"},
            {"name": "Kitchen Walk-in Freezer", "category": "kitchen", "issue": "Temperature alarm triggered", "severity": "critical"},
            {"name": "Backup Generator", "category": "electrical", "issue": "Scheduled maintenance due", "severity": "low"},
        ]

        eq_count = 0
        eq_statuses = ["pending", "in_progress", "resolved"]

        for i, template in enumerate(equipment_templates):
            status = eq_statuses[i % len(eq_statuses)]

            eq = EquipmentIssues(
                issue_number=f"EQ-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                equipment_name=template["name"],
                equipment_category=template["category"],
                location="Main Building",
                issue_type="Malfunction",
                issue_description=template["issue"],
                severity=template["severity"],
                status=status,
                reported_by=john.id,
                reported_at=datetime.now() - timedelta(days=i),
                assigned_to=john.id if status != "pending" else None,
                accepted_at=datetime.now() - timedelta(hours=12) if status != "pending" else None,
                resolved_at=datetime.now() - timedelta(hours=2) if status == "resolved" else None,
                resolution_notes="Equipment serviced and operational" if status == "resolved" else None,
                affects_operations=template["severity"] in ["high", "critical"],
            )
            session.add(eq)
            eq_count += 1

        await session.commit()
        print(f"  [OK] Created {wo_count} work orders and {eq_count} equipment issues")

        # ========== STEP 6: Create Runner Pickups and Deliveries ==========
        print("\n[6/6] Creating runner pickups and deliveries for Alex...")

        alex = staff_objects["runner"]

        # RUNNER WORKFLOW:
        # Pickup: pending -> in_progress -> completed
        # Delivery: pending -> in_transit -> delivered

        pickup_templates = [
            {"type": "luggage", "items": "2 suitcases, 1 carry-on bag", "dest": "Bell Storage"},
            {"type": "laundry", "items": "Express laundry bag - suits and shirts", "dest": "Laundry Room"},
            {"type": "package", "items": "3 Amazon packages", "dest": "Guest Room"},
            {"type": "luggage", "items": "Golf clubs and 1 travel bag", "dest": "Bell Desk"},
            {"type": "amenity_request", "items": "Extra pillows and blankets", "dest": "Guest Room"},
        ]

        pickup_count = 0
        pickup_statuses = ["pending", "in_progress", "completed"]

        for i, template in enumerate(pickup_templates):
            room = rooms[i + 5]  # Different rooms than housekeeping
            status = pickup_statuses[i % len(pickup_statuses)]

            pickup = RunnerPickupRequest(
                request_number=f"PU-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                room_id=room.id,
                room_number=room.number,
                guest_name=f"Guest in Room {room.number}",
                pickup_type=template["type"],
                items_description=template["items"],
                item_count=random.randint(1, 4),
                pickup_location=f"Room {room.number}",
                destination=template["dest"],
                scheduled_time=datetime.now() + timedelta(hours=i),
                priority="normal" if i % 2 == 0 else "high",
                status=status,
                requested_by="Front Desk",
                requested_at=datetime.now() - timedelta(hours=i),
                assigned_to=alex.id if status != "pending" else None,
                accepted_at=datetime.now() - timedelta(minutes=30) if status != "pending" else None,
                completed_at=datetime.now() - timedelta(minutes=10) if status == "completed" else None,
                duration_minutes=15 if status == "completed" else None,
            )
            session.add(pickup)
            pickup_count += 1

        delivery_templates = [
            {"type": "room_service", "items": "Breakfast: Eggs Benedict, Fresh Juice, Coffee", "origin": "Kitchen"},
            {"type": "room_service", "items": "Dinner: Steak, Wine, Dessert", "origin": "Kitchen"},
            {"type": "package", "items": "FedEx overnight package", "origin": "Mail Room"},
            {"type": "laundry", "items": "Pressed suits and dry cleaning", "origin": "Laundry"},
            {"type": "amenity", "items": "Welcome amenity basket", "origin": "Concierge"},
        ]

        delivery_count = 0
        delivery_statuses = ["pending", "in_transit", "delivered"]

        for i, template in enumerate(delivery_templates):
            room = rooms[i + 10]  # Different rooms
            status = delivery_statuses[i % len(delivery_statuses)]

            delivery = RunnerDelivery(
                delivery_number=f"DL-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                delivery_type=template["type"],
                room_id=room.id,
                room_number=room.number,
                guest_name=f"Guest in Room {room.number}",
                items_description=template["items"],
                item_count=random.randint(1, 3),
                origin_location=template["origin"],
                destination_location=f"Room {room.number}",
                priority="high" if template["type"] == "room_service" else "normal",
                status=status,
                ordered_at=datetime.now() - timedelta(hours=i),
                assigned_to=alex.id if status != "pending" else None,
                accepted_at=datetime.now() - timedelta(minutes=20) if status != "pending" else None,
                picked_up_at=datetime.now() - timedelta(minutes=15) if status in ["in_transit", "delivered"] else None,
                delivered_at=datetime.now() - timedelta(minutes=5) if status == "delivered" else None,
                estimated_delivery_time=datetime.now() + timedelta(minutes=30),
                duration_minutes=12 if status == "delivered" else None,
                temperature_sensitive=template["type"] == "room_service",
            )
            session.add(delivery)
            delivery_count += 1

        await session.commit()
        print(f"  [OK] Created {pickup_count} pickups and {delivery_count} deliveries")

        # ========== STEP 7: Create Staff Notifications ==========
        print("\n[7/7] Creating staff notifications...")

        # We need user IDs for notifications (staff_id in StaffNotification is actually user_id)
        # Get user IDs for each staff member
        for dept, staff_member in staff_objects.items():
            # Get the corresponding user
            result = await session.exec(select(User).where(User.id == staff_member.user_id))
            user = result.first()
            if not user:
                continue

            # Create notifications based on department
            if dept == "housekeeping":
                notifications = [
                    {
                        "type": "task_assigned",
                        "title": "New Cleaning Task Assigned",
                        "message": "Room 505 checkout clean has been assigned to you. Priority: High",
                        "is_read": False,
                    },
                    {
                        "type": "task_reminder",
                        "title": "Task Reminder",
                        "message": "Room 601 turndown service is due in 30 minutes",
                        "is_read": False,
                    },
                    {
                        "type": "system",
                        "title": "Shift Starting Soon",
                        "message": "Your morning shift starts in 15 minutes. Please clock in.",
                        "is_read": True,
                    },
                    {
                        "type": "info",
                        "title": "VIP Guest Arriving",
                        "message": "Suite 801 - VIP guest arriving at 3pm. Extra attention required.",
                        "is_read": False,
                    },
                ]
            elif dept == "maintenance":
                notifications = [
                    {
                        "type": "task_assigned",
                        "title": "New Work Order Assigned",
                        "message": "WO-001: AC Unit repair in Room 502. Priority: High",
                        "is_read": False,
                    },
                    {
                        "type": "alert",
                        "title": "Equipment Alert",
                        "message": "Elevator #2 requires immediate inspection - unusual noise reported",
                        "is_read": False,
                    },
                    {
                        "type": "system",
                        "title": "Maintenance Schedule Updated",
                        "message": "Pool heater inspection has been moved to tomorrow 9am",
                        "is_read": True,
                    },
                ]
            else:  # runner
                notifications = [
                    {
                        "type": "task_assigned",
                        "title": "New Pickup Request",
                        "message": "Luggage pickup from Room 612. 2 suitcases, 1 carry-on.",
                        "is_read": False,
                    },
                    {
                        "type": "task_assigned",
                        "title": "Room Service Delivery",
                        "message": "Breakfast delivery to Room 715. Temperature sensitive - deliver within 10 mins.",
                        "is_read": False,
                    },
                    {
                        "type": "info",
                        "title": "Package Arrived",
                        "message": "FedEx package received for Room 508. Guest requested immediate delivery.",
                        "is_read": False,
                    },
                    {
                        "type": "system",
                        "title": "Daily Briefing",
                        "message": "Morning briefing completed. 5 deliveries and 3 pickups scheduled for today.",
                        "is_read": True,
                    },
                ]

            notif_count = 0
            for i, n in enumerate(notifications):
                notif = StaffNotification(
                    staff_id=user.id,  # This is actually user_id per the FK definition
                    task_id=None,  # Not linked to specific tasks
                    notification_type=n["type"],
                    title=n["title"],
                    message=n["message"],
                    is_read=n["is_read"],
                    read_at=datetime.now() - timedelta(hours=1) if n["is_read"] else None,
                    created_at=datetime.now() - timedelta(hours=i * 2),
                )
                session.add(notif)
                notif_count += 1

            print(f"  [OK] Created {notif_count} notifications for {staff_member.name}")

        await session.commit()

        # ========== SUMMARY ==========
        print("\n" + "=" * 60)
        print("STAFF DATA SEEDED SUCCESSFULLY!")
        print("=" * 60)
        print("\nSummary:")
        print("   Staff Members: 3")
        print(f"   Housekeeping Tasks: {task_count}")
        print(f"   Work Orders: {wo_count}")
        print(f"   Equipment Issues: {eq_count}")
        print(f"   Pickup Requests: {pickup_count}")
        print(f"   Deliveries: {delivery_count}")
        print("   Staff Notifications: ~11 (per staff member)")
        print("\nStaff Portal Login Credentials:")
        print("\n   HOUSEKEEPING:")
        print("      Email: maria@glimmora.local")
        print("      Password: 123456")
        print("      Role: Housekeeping | Floors 5-8")
        print("\n   MAINTENANCE:")
        print("      Email: john@glimmora.local")
        print("      Password: 123456")
        print("      Role: Maintenance Technician | HVAC & Electrical")
        print("\n   RUNNER:")
        print("      Email: alex@glimmora.local")
        print("      Password: 123456")
        print("      Role: Runner/Bell Staff | Guest Services")
        print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(seed_clean_staff())
