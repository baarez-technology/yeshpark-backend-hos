"""
Seed script for Staff, Maintenance, and Housekeeping data
"""
import asyncio
import json
import random
from datetime import date, datetime, time, timedelta
from app.db.session import async_session_maker, init_db
from app.core.security import get_password_hash
from app.models.user import User
from app.models.staff import Staff, StaffSchedule
from app.models.operations import HousekeepingTask, MaintenanceRequest, LostFound, LinenInventory
from app.models.inventory import Room
from sqlmodel import select


async def seed_all():
    """Seed staff, maintenance, and housekeeping data"""
    await init_db()
    async with async_session_maker() as session:
        print("=" * 60)
        print("Seeding Staff, Maintenance, and Housekeeping Data")
        print("=" * 60)

        # Get existing rooms and users
        rooms = (await session.exec(select(Room))).all()
        users = (await session.exec(select(User))).all()

        print(f"Found {len(rooms)} rooms and {len(users)} users")

        # ========== STAFF ==========
        print("\n[1/5] Creating staff members...")

        staff_data_list = [
            # Housekeeping
            {"name": "Maria Garcia", "email": "maria.garcia@glimmora.local", "phone": "+1-555-300-0001",
             "role": "housekeeper", "department": "housekeeping", "specialty": "Deep Cleaning",
             "shift": "morning", "shift_start": time(7, 0), "shift_end": time(15, 0),
             "performance_rating": 4.8, "hourly_rate": 18.0},
            {"name": "James Wilson", "email": "james.wilson@glimmora.local", "phone": "+1-555-300-0002",
             "role": "housekeeper", "department": "housekeeping", "specialty": "Turndown Service",
             "shift": "afternoon", "shift_start": time(15, 0), "shift_end": time(23, 0),
             "performance_rating": 4.6, "hourly_rate": 17.5},
            {"name": "Ana Martinez", "email": "ana.martinez@glimmora.local", "phone": "+1-555-300-0003",
             "role": "housekeeper", "department": "housekeeping", "specialty": "Laundry",
             "shift": "morning", "shift_start": time(6, 0), "shift_end": time(14, 0),
             "performance_rating": 4.7, "hourly_rate": 17.0},
            {"name": "Lisa Chen", "email": "lisa.chen@glimmora.local", "phone": "+1-555-300-0004",
             "role": "housekeeper", "department": "housekeeping", "specialty": "Suite Prep",
             "shift": "morning", "shift_start": time(7, 0), "shift_end": time(15, 0),
             "performance_rating": 4.9, "hourly_rate": 19.0},
            # Maintenance
            {"name": "Robert Brown", "email": "robert.brown@glimmora.local", "phone": "+1-555-300-0010",
             "role": "technician", "department": "maintenance", "specialty": "Electrical",
             "shift": "morning", "shift_start": time(7, 0), "shift_end": time(15, 0),
             "performance_rating": 4.7, "hourly_rate": 28.0},
            {"name": "William Davis", "email": "william.davis@glimmora.local", "phone": "+1-555-300-0011",
             "role": "technician", "department": "maintenance", "specialty": "Plumbing",
             "shift": "afternoon", "shift_start": time(15, 0), "shift_end": time(23, 0),
             "performance_rating": 4.5, "hourly_rate": 26.0},
            {"name": "Thomas Anderson", "email": "thomas.anderson@glimmora.local", "phone": "+1-555-300-0012",
             "role": "technician", "department": "maintenance", "specialty": "HVAC",
             "shift": "morning", "shift_start": time(6, 0), "shift_end": time(14, 0),
             "performance_rating": 4.8, "hourly_rate": 30.0},
            {"name": "Kevin Taylor", "email": "kevin.taylor@glimmora.local", "phone": "+1-555-300-0013",
             "role": "technician", "department": "maintenance", "specialty": "General",
             "shift": "night", "shift_start": time(23, 0), "shift_end": time(7, 0),
             "performance_rating": 4.4, "hourly_rate": 25.0},
            # Front Desk
            {"name": "Sarah Johnson", "email": "sarah.johnson@glimmora.local", "phone": "+1-555-300-0020",
             "role": "front_desk_agent", "department": "frontdesk", "specialty": "VIP Relations",
             "shift": "morning", "shift_start": time(7, 0), "shift_end": time(15, 0),
             "performance_rating": 4.9, "hourly_rate": 22.0},
            {"name": "Michael Chen", "email": "michael.chen@glimmora.local", "phone": "+1-555-300-0021",
             "role": "front_desk_agent", "department": "frontdesk", "specialty": "Multilingual",
             "shift": "afternoon", "shift_start": time(15, 0), "shift_end": time(23, 0),
             "performance_rating": 4.7, "hourly_rate": 21.0},
            {"name": "Emily Rodriguez", "email": "emily.rodriguez@glimmora.local", "phone": "+1-555-300-0022",
             "role": "front_desk_agent", "department": "frontdesk", "specialty": "Night Audit",
             "shift": "night", "shift_start": time(23, 0), "shift_end": time(7, 0),
             "performance_rating": 4.5, "hourly_rate": 24.0},
            # Management
            {"name": "Jennifer Lee", "email": "jennifer.lee@glimmora.local", "phone": "+1-555-300-0030",
             "role": "manager", "department": "management", "specialty": "Operations",
             "shift": "morning", "shift_start": time(8, 0), "shift_end": time(17, 0),
             "performance_rating": 4.9, "hourly_rate": 45.0},
        ]

        staff_count = 0
        staff_objects = []

        for idx, staff_info in enumerate(staff_data_list, 1):
            # Check if staff exists
            existing_staff = (await session.exec(select(Staff).where(Staff.email == staff_info["email"]))).first()
            if existing_staff:
                staff_objects.append(existing_staff)
                print(f"  -> Staff exists: {staff_info['name']}")
                continue

            # Check if user exists
            existing_user = (await session.exec(select(User).where(User.email == staff_info["email"]))).first()
            if existing_user:
                user_id = existing_user.id
            else:
                # Create user
                user = User(
                    email=staff_info["email"],
                    full_name=staff_info["name"],
                    hashed_password=get_password_hash("staff123"),
                    is_active=True,
                    role=staff_info["role"],
                    phone=staff_info.get("phone"),
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                print(f"  + Created user: {staff_info['name']}")

            # Create staff record
            staff = Staff(
                user_id=user_id,
                employee_id=f"EMP-{100 + idx:03d}",
                name=staff_info["name"],
                email=staff_info["email"],
                phone=staff_info.get("phone"),
                role=staff_info["role"],
                department=staff_info["department"],
                specialty=staff_info.get("specialty"),
                status="active",
                shift=staff_info.get("shift"),
                shift_start=staff_info.get("shift_start"),
                shift_end=staff_info.get("shift_end"),
                performance_rating=staff_info.get("performance_rating"),
                hourly_rate=staff_info.get("hourly_rate"),
                hire_date=date.today() - timedelta(days=365 + idx * 30),
                clocked_in=idx % 3 != 0,
                skills=json.dumps(["Customer Service", "Communication"]),
                languages_spoken=json.dumps(["English"]),
            )
            session.add(staff)
            await session.flush()
            staff_objects.append(staff)
            staff_count += 1
            print(f"  + Created staff: {staff_info['name']} ({staff_info['department']})")

        await session.commit()
        print(f"  Total staff created: {staff_count}")

        # ========== HOUSEKEEPING TASKS ==========
        print("\n[2/5] Creating housekeeping tasks...")

        existing_tasks = (await session.exec(select(HousekeepingTask))).all()
        if existing_tasks:
            print(f"  -> Tasks already exist ({len(existing_tasks)} found)")
        else:
            hk_staff = [s for s in staff_objects if s.department == "housekeeping"]
            task_types = ["clean", "deep_clean", "inspect", "turndown"]
            priorities = ["low", "normal", "high", "urgent"]
            statuses = ["pending", "in_progress", "done"]

            task_count = 0
            now = datetime.utcnow()

            for idx, room in enumerate(rooms):
                task_type = task_types[idx % len(task_types)]
                priority = priorities[idx % len(priorities)]
                status = statuses[idx % len(statuses)]
                assigned = hk_staff[idx % len(hk_staff)] if hk_staff else None

                started_at = None
                completed_at = None
                actual_duration = None

                if status == "in_progress":
                    started_at = now - timedelta(minutes=30 + idx * 5)
                elif status == "done":
                    started_at = now - timedelta(hours=2, minutes=idx * 3)
                    completed_at = now - timedelta(hours=1, minutes=idx * 2)
                    actual_duration = 45 + (idx % 30)

                task = HousekeepingTask(
                    room_id=room.id,
                    task_type=task_type,
                    status=status,
                    priority=priority,
                    assigned_to=assigned.id if assigned else None,
                    scheduled_for=now + timedelta(hours=idx % 8),
                    started_at=started_at,
                    completed_at=completed_at,
                    estimated_duration=30 + (idx % 30),
                    actual_duration=actual_duration,
                    notes=f"Task for room {room.number}" if idx % 3 == 0 else None,
                )
                session.add(task)
                task_count += 1

            await session.commit()
            print(f"  Total tasks created: {task_count}")

        # ========== MAINTENANCE REQUESTS ==========
        print("\n[3/5] Creating maintenance requests...")

        existing_maintenance = (await session.exec(select(MaintenanceRequest))).all()
        if existing_maintenance:
            print(f"  -> Maintenance requests already exist ({len(existing_maintenance)} found)")
        else:
            maint_staff = [s for s in staff_objects if s.department == "maintenance"]
            issues = [
                ("AC Not Cooling", "hvac", "high"),
                ("Faucet Dripping", "plumbing", "medium"),
                ("Light Flickering", "electrical", "low"),
                ("TV Remote Broken", "appliance", "low"),
                ("Window Stuck", "general", "high"),
                ("Fridge Noisy", "appliance", "medium"),
                ("Fan Not Working", "hvac", "medium"),
                ("Door Lock Issue", "security", "emergency"),
                ("Toilet Running", "plumbing", "high"),
                ("Heater Broken", "hvac", "emergency"),
            ]
            statuses = ["pending", "assigned", "in_progress", "completed", "on_hold"]

            maint_count = 0
            for idx, room in enumerate(rooms[:15]):
                issue, category, priority = issues[idx % len(issues)]
                status = statuses[idx % len(statuses)]
                assigned = maint_staff[idx % len(maint_staff)] if maint_staff and status in ["assigned", "in_progress", "completed"] else None

                work_order_id = f"WO-{2024001 + idx}"

                # Ensure proper chronological order: reported_at < started_at < completed_at
                reported_at = datetime.utcnow() - timedelta(days=idx % 7, hours=random.randint(0, 12))

                started_at = None
                completed_at = None
                if status == "in_progress":
                    # Started 1-4 hours after being reported
                    started_at = reported_at + timedelta(hours=random.randint(1, 4))
                elif status == "completed":
                    # Started 1-8 hours after being reported
                    started_at = reported_at + timedelta(hours=random.randint(1, 8))
                    # Completed 2-12 hours after starting
                    completed_at = started_at + timedelta(hours=random.randint(2, 12))

                request = MaintenanceRequest(
                    work_order_id=work_order_id,
                    room_id=room.id,
                    room_number=room.number,
                    location=f"Room {room.number}",
                    title=issue,
                    category=category,
                    issue_type=category,
                    priority=priority,
                    issue=issue,
                    description=f"{issue} in Room {room.number}. Guest reported the issue and requested immediate attention.",
                    status=status,
                    severity=priority,
                    assigned_to=assigned.id if assigned else None,
                    reported_by=maint_staff[0].id if maint_staff else None,
                    reported_at=reported_at,
                    started_at=started_at,
                    completed_at=completed_at,
                    estimated_duration=random.randint(30, 180),
                    is_out_of_order=priority == "emergency" and status not in ["completed"],
                )
                session.add(request)
                maint_count += 1

            # Common areas
            common_issues = [
                ("Lobby Elevator Noise", "elevator", "high", "Lobby"),
                ("Pool Heater Issue", "hvac", "emergency", "Pool Area"),
                ("Parking Light Out", "electrical", "low", "Parking Level 1"),
                ("Gym Treadmill Malfunction", "equipment", "medium", "Fitness Center"),
                ("Conference Room Projector", "electrical", "high", "Conference Room A"),
                ("Restaurant Fridge", "appliance", "emergency", "Restaurant Kitchen"),
            ]
            for idx, (issue, category, priority, location) in enumerate(common_issues):
                request = MaintenanceRequest(
                    work_order_id=f"WO-{2024100 + idx}",
                    room_id=None,
                    room_number=None,
                    location=location,
                    title=issue,
                    category=category,
                    issue_type=category,
                    priority=priority,
                    issue=issue,
                    description=f"Common area maintenance: {issue}. Located in {location}.",
                    status="pending" if idx % 2 == 0 else "in_progress",
                    assigned_to=maint_staff[idx % len(maint_staff)].id if maint_staff and idx % 2 == 1 else None,
                    reported_by=maint_staff[0].id if maint_staff else None,
                    reported_at=datetime.utcnow() - timedelta(days=idx),
                )
                session.add(request)
                maint_count += 1

            await session.commit()
            print(f"  Total maintenance requests created: {maint_count}")

        # ========== LOST AND FOUND ==========
        print("\n[4/5] Creating lost and found items...")

        existing_lf = (await session.exec(select(LostFound))).all()
        if existing_lf:
            print(f"  -> Lost/found items already exist ({len(existing_lf)} found)")
        else:
            lf_items = [
                ("Silver Rolex Watch", "Room 501 Nightstand", "Safe Box A1", "stored"),
                ("Black Leather Wallet", "Lobby Area", "Reception", "stored"),
                ("iPhone 14 Pro", "Pool Lounger", "Safe Box A2", "stored"),
                ("Blue Umbrella", "Restaurant", "L&F Closet", "claimed"),
                ("Gold Earring", "Room 305 Bath", "Safe Box A3", "stored"),
                ("Glasses Ray-Ban", "Gym Locker", "L&F Closet", "stored"),
                ("Kids Teddy Bear", "Play Area", "L&F Closet", "claimed"),
                ("BMW Car Keys", "Parking Level 2", "Safe Box A4", "stored"),
            ]

            lf_count = 0
            for idx, (desc, location, storage, status) in enumerate(lf_items):
                item = LostFound(
                    item_description=desc,
                    location_found=location,
                    room_id=rooms[idx % len(rooms)].id if "Room" in location else None,
                    found_by=users[idx % len(users)].id if users else None,
                    found_date=date.today() - timedelta(days=idx * 3),
                    storage_location=storage,
                    status=status,
                )
                session.add(item)
                lf_count += 1

            await session.commit()
            print(f"  Total lost/found items created: {lf_count}")

        # ========== LINEN INVENTORY ==========
        print("\n[5/5] Creating linen inventory...")

        existing_linen = (await session.exec(select(LinenInventory))).all()
        if existing_linen:
            print(f"  -> Linen inventory already exists ({len(existing_linen)} found)")
        else:
            linen_items = [
                ("King Sheets", 200, "Main Linen Room"),
                ("Queen Sheets", 300, "Main Linen Room"),
                ("Bath Towels", 500, "Main Linen Room"),
                ("Hand Towels", 600, "Main Linen Room"),
                ("Washcloths", 800, "Main Linen Room"),
                ("Pillowcases", 400, "Floor 10 Storage"),
                ("Duvet Covers", 150, "Floor 15 Storage"),
                ("Bath Mats", 250, "Main Linen Room"),
                ("Pool Towels", 350, "Pool Storage"),
                ("Bathrobes", 100, "VIP Storage"),
            ]

            linen_count = 0
            for item_type, qty, location in linen_items:
                item = LinenInventory(
                    item_type=item_type,
                    quantity=qty,
                    location=location,
                    status="available",
                    last_updated=datetime.utcnow(),
                )
                session.add(item)
                linen_count += 1

            await session.commit()
            print(f"  Total linen items created: {linen_count}")

        print("\n" + "=" * 60)
        print("Database seeding completed!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed_all())
