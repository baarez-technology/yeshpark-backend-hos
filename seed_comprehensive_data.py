"""
Comprehensive Data Seeding Script for Glimmora Hotel Management System
This script populates all database tables with realistic test data.
"""
import sqlite3
import random
from datetime import datetime, timedelta
import json

# Connect to database
conn = sqlite3.connect('glimmora.db')
cursor = conn.cursor()

print("=" * 60)
print("GLIMMORA COMPREHENSIVE DATA SEEDING")
print("=" * 60)

# Helper functions
def random_date(start_days_ago, end_days_ago=0):
    """Generate random date between start_days_ago and end_days_ago"""
    days = random.randint(end_days_ago, start_days_ago)
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

def random_datetime(start_days_ago, end_days_ago=0):
    """Generate random datetime"""
    days = random.randint(end_days_ago, start_days_ago)
    hours = random.randint(0, 23)
    minutes = random.randint(0, 59)
    dt = datetime.now() - timedelta(days=days, hours=hours, minutes=minutes)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def random_future_date(start_days=1, end_days=30):
    """Generate random future date"""
    days = random.randint(start_days, end_days)
    return (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

def random_future_datetime(start_days=1, end_days=30):
    """Generate random future datetime"""
    days = random.randint(start_days, end_days)
    hours = random.randint(8, 18)
    minutes = random.randint(0, 59)
    dt = datetime.now() + timedelta(days=days, hours=hours, minutes=minutes)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

# Get existing data for foreign keys
cursor.execute("SELECT id FROM rooms")
room_ids = [r[0] for r in cursor.fetchall()]

cursor.execute("SELECT id, number FROM rooms")
rooms_data = cursor.fetchall()
room_id_to_number = {r[0]: r[1] for r in rooms_data}

cursor.execute("SELECT id FROM guests")
guest_ids = [g[0] for g in cursor.fetchall()]

cursor.execute("SELECT id FROM users WHERE role IN ('housekeeping', 'maintenance', 'runner', 'front_desk', 'manager')")
staff_user_ids = [u[0] for u in cursor.fetchall()]

cursor.execute("SELECT id FROM bookings")
booking_ids = [b[0] for b in cursor.fetchall()]

cursor.execute("SELECT id FROM room_types")
room_type_ids = [r[0] for r in cursor.fetchall()]

print(f"Found: {len(room_ids)} rooms, {len(guest_ids)} guests, {len(staff_user_ids)} staff, {len(booking_ids)} bookings")

# ========== 1. HOUSEKEEPING TASKS ==========
print("\n[1/12] Seeding housekeeping_tasks...")
task_types = ['daily_clean', 'checkout_clean', 'deep_clean', 'turndown', 'inspection']
priorities = ['low', 'normal', 'high', 'urgent']
statuses = ['pending', 'in_progress', 'completed', 'verified']

for i in range(40):
    room_id = random.choice(room_ids) if room_ids else 1
    assigned_to = random.choice(staff_user_ids) if staff_user_ids else None
    task_type = random.choice(task_types)
    priority = random.choice(priorities)
    status = random.choice(statuses)
    created = random_datetime(30, 0)
    scheduled = random_future_datetime(0, 7)

    cursor.execute("""
        INSERT OR IGNORE INTO housekeeping_tasks
        (room_id, task_type, priority, status, assigned_to, notes,
         scheduled_for, estimated_duration, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (room_id, task_type, priority, status, assigned_to,
          f"Task #{i+1}: {task_type} for room", scheduled,
          random.randint(15, 60), created, created))

print("   Added 40 housekeeping tasks")

# ========== 2. MAINTENANCE REQUESTS ==========
print("\n[2/12] Seeding maintenancerequest...")
categories = ['plumbing', 'electrical', 'hvac', 'furniture', 'appliance', 'structural', 'other']
maint_statuses = ['open', 'in_progress', 'completed', 'cancelled']
maint_priorities = ['low', 'medium', 'high', 'critical']
severities = ['minor', 'moderate', 'major', 'critical']

issues = [
    ("AC not cooling properly", "hvac"),
    ("Leaky faucet in bathroom", "plumbing"),
    ("TV remote not working", "appliance"),
    ("Door lock malfunction", "other"),
    ("Light fixture flickering", "electrical"),
    ("Toilet running continuously", "plumbing"),
    ("Window won't close properly", "structural"),
    ("Mini fridge not cooling", "appliance"),
    ("Shower drain clogged", "plumbing"),
    ("Smoke detector beeping", "electrical")
]

for i in range(35):
    room_id = random.choice(room_ids) if room_ids else 1
    room_number = room_id_to_number.get(room_id, '101')
    issue, category = random.choice(issues)
    status = random.choice(maint_statuses)
    priority = random.choice(maint_priorities)
    severity = random.choice(severities)
    created = random_datetime(60, 0)
    work_order = f"WO-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}"

    cursor.execute("""
        INSERT OR IGNORE INTO maintenancerequest
        (work_order_id, room_id, room_number, location, category, priority,
         issue, description, status, severity, assigned_to, reported_by,
         reported_at, estimated_cost, is_out_of_order, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (work_order, room_id, room_number, f"Room {room_number}", category, priority,
          issue, f"Guest reported: {issue}", status, severity,
          random.choice(staff_user_ids) if staff_user_ids else None,
          random.choice(guest_ids) if guest_ids else None,
          created, round(random.uniform(4000, 41500), 2),
          priority == 'critical', created, created))

print("   Added 35 maintenance requests")

# ========== 3. REVIEWS ==========
print("\n[3/12] Seeding reviews...")
sources = ['google', 'tripadvisor', 'booking.com', 'expedia', 'yelp', 'direct']
sentiments = ['positive', 'neutral', 'negative']

review_data = [
    ("Excellent stay!", "The staff was incredibly helpful and the room was spotless.", "Great service, clean room", "None"),
    ("Beautiful hotel", "Amazing views and wonderful atmosphere. Will definitely come back.", "Views, atmosphere", "Bit pricey"),
    ("Good location", "Good location but the room was a bit small for the price.", "Location", "Small room"),
    ("Outstanding service", "From check-in to check-out, exceptional experience.", "Everything", "None"),
    ("Great breakfast", "The breakfast buffet was exceptional. Great variety.", "Breakfast variety", "Could use more healthy options"),
    ("Mixed experience", "Room was clean but the AC was quite noisy at night.", "Clean room", "Noisy AC"),
    ("Perfect for business", "Fast WiFi and quiet environment. Perfect for work.", "WiFi, quiet", "Limited dining options"),
    ("Lovely boutique hotel", "Charming decor and friendly staff.", "Decor, staff", "Parking limited"),
    ("Disappointing", "Room wasn't ready on time despite early check-in request.", "Location", "Late room, poor communication"),
    ("Great value", "Excellent value for money. The spa was top-notch.", "Value, spa", "Restaurant closed early")
]

for i in range(50):
    guest_id = random.choice(guest_ids) if guest_ids else None
    booking_id = random.choice(booking_ids) if booking_ids else None
    room_id = random.choice(room_ids) if room_ids else None
    source = random.choice(sources)
    rating = random.choices([5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0], weights=[30, 25, 20, 10, 8, 5, 2])[0]
    created = random_datetime(90, 0)
    title, comment, pros, cons = random.choice(review_data)

    sentiment = 'positive' if rating >= 4.0 else 'neutral' if rating >= 3.0 else 'negative'

    cursor.execute("""
        INSERT OR IGNORE INTO reviews
        (guest_id, booking_id, room_id, source, overall_rating,
         cleanliness_rating, service_rating, location_rating, value_rating, amenities_rating,
         title, comment, pros, cons, sentiment,
         is_verified, is_featured, is_public, helpful_count, review_date, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (guest_id, booking_id, room_id, source, rating,
          round(rating + random.uniform(-0.5, 0.5), 1),
          round(rating + random.uniform(-0.5, 0.5), 1),
          round(rating + random.uniform(-0.3, 0.3), 1),
          round(rating + random.uniform(-0.5, 0.5), 1),
          round(rating + random.uniform(-0.5, 0.5), 1),
          title, comment, pros, cons, sentiment,
          True, rating >= 4.5, True, random.randint(0, 50),
          created, created, created))

print("   Added 50 reviews")

# ========== 4. DAILY METRICS ==========
print("\n[4/12] Seeding daily_metrics...")
base_date = datetime.now() - timedelta(days=90)

for i in range(90):
    metric_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')

    total_rooms = 26
    ooo_rooms = random.randint(0, 2)
    available_rooms = total_rooms - ooo_rooms
    occupied = random.randint(8, min(24, available_rooms))
    occupancy = round((occupied / available_rooms) * 100, 2)
    adr = round(random.uniform(15000, 29000), 2)
    revpar = round(adr * (occupancy / 100), 2)
    room_revenue = round(occupied * adr, 2)
    ancillary = round(random.uniform(16500, 125000), 2)
    total_revenue = room_revenue + ancillary

    cursor.execute("""
        INSERT OR IGNORE INTO daily_metrics
        (metric_date, total_rooms, occupied_rooms, available_rooms, ooo_rooms,
         occupancy_percentage, adr, revpar, total_revenue, room_revenue, ancillary_revenue,
         arrivals, departures, in_house_guests, no_shows, cancellations, walk_ins, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (metric_date, total_rooms, occupied, available_rooms, ooo_rooms,
          occupancy, adr, revpar, total_revenue, room_revenue, ancillary,
          random.randint(2, 8), random.randint(2, 8), occupied + random.randint(0, 5),
          random.randint(0, 2), random.randint(0, 3), random.randint(0, 2),
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

print("   Added 90 days of daily metrics")

# ========== 5. STAFF TASKS ==========
print("\n[5/12] Seeding stafftask...")
task_types = ['guest_request', 'room_service', 'concierge', 'front_desk', 'vip_service']
task_statuses = ['pending', 'in_progress', 'completed', 'cancelled']

task_titles = [
    "Complete guest registration for VIP arrival",
    "Prepare welcome amenities for suite guest",
    "Follow up on special dietary requirements",
    "Coordinate airport transfer service",
    "Process late checkout request",
    "Handle guest complaint resolution",
    "Prepare daily occupancy report",
    "Schedule maintenance inspection",
    "Arrange conference room setup",
    "Update inventory records"
]

for i in range(45):
    assigned_to = random.choice(staff_user_ids) if staff_user_ids else 1
    room_id = random.choice(room_ids) if room_ids else None
    room_number = room_id_to_number.get(room_id) if room_id else None
    guest_id = random.choice(guest_ids) if guest_ids else None
    booking_id = random.choice(booking_ids) if booking_ids else None
    task_type = random.choice(task_types)
    status = random.choice(task_statuses)
    priority = random.choice(['low', 'medium', 'high', 'urgent'])
    created = random_datetime(30, 0)
    scheduled = random_future_datetime(0, 3)
    title = random.choice(task_titles)

    cursor.execute("""
        INSERT OR IGNORE INTO stafftask
        (task_type, title, description, room_number, room_id, booking_id, guest_id,
         priority, status, assigned_to, scheduled_for, estimated_duration,
         notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (task_type, title, f"Details: {title}", room_number, room_id, booking_id, guest_id,
          priority, status, assigned_to, scheduled, random.randint(10, 60),
          "Auto-generated task", created, created))

print("   Added 45 staff tasks")

# ========== 6. RUNNER DELIVERIES ==========
print("\n[6/12] Seeding runner_deliveries...")
delivery_types = ['room_service', 'amenity', 'luggage', 'laundry', 'package', 'document']
delivery_statuses = ['pending', 'assigned', 'picked_up', 'in_transit', 'delivered', 'failed']
priorities = ['low', 'normal', 'high', 'urgent']

items_by_type = {
    'room_service': ['Club Sandwich', 'Caesar Salad', 'Burger & Fries', 'Pasta Carbonara', 'Steak Dinner'],
    'amenity': ['Extra Towels (4)', 'Pillow Set', 'Toiletries Kit', 'Bathrobe', 'Iron & Board'],
    'luggage': ['2 Suitcases', 'Carry-on Bag', 'Golf Clubs', '3 Bags Total', '1 Large Case'],
    'laundry': ['Dry Cleaning - 3 items', 'Laundry - 5 items', 'Express Press - 2 items'],
    'package': ['Amazon Package', 'FedEx Delivery', 'Gift Box', 'Documents'],
    'document': ['Fax Documents', 'Printed Tickets', 'Confirmation Letter', 'Invoice']
}

origins = ['Front Desk', 'Kitchen', 'Laundry Room', 'Storage', 'Concierge Desk', 'Guest Services']

for i in range(40):
    room_id = random.choice(room_ids) if room_ids else 1
    room_number = room_id_to_number.get(room_id, '101')
    guest_id = random.choice(guest_ids) if guest_ids else None
    runner_id = random.choice(staff_user_ids) if staff_user_ids else None
    d_type = random.choice(delivery_types)
    status = random.choice(delivery_statuses)
    priority = random.choice(priorities)
    created = random_datetime(14, 0)
    delivery_num = f"DLV-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}"

    cursor.execute("""
        INSERT OR IGNORE INTO runner_deliveries
        (delivery_number, delivery_type, room_id, room_number, guest_id,
         items_description, item_count, origin_location, destination_location,
         priority, status, ordered_at, assigned_to, special_instructions,
         signature_required, temperature_sensitive, fragile, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (delivery_num, d_type, room_id, room_number, guest_id,
          random.choice(items_by_type[d_type]), random.randint(1, 5),
          random.choice(origins), f"Room {room_number}",
          priority, status, created, runner_id,
          random.choice(['Handle with care', 'Urgent', 'Leave at door', None]),
          d_type in ['document', 'package'], d_type == 'room_service',
          d_type in ['package', 'amenity'], created, created))

print("   Added 40 runner deliveries")

# ========== 7. NIGHT AUDIT ==========
print("\n[7/12] Seeding nightaudit...")
base_date = datetime.now() - timedelta(days=30)

for i in range(30):
    audit_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')

    occupied = random.randint(10, 24)
    occupancy_rate = round((occupied / 26) * 100, 2)
    revenue = round(occupied * random.uniform(16500, 29000) + random.uniform(41500, 207500), 2)

    cursor.execute("""
        INSERT OR IGNORE INTO nightaudit
        (audit_date, run_at, run_by, status, occupancy_rate, revenue,
         arrivals, departures, in_house, no_shows, walk_ins, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (audit_date, f"{audit_date} 23:30:00",
          random.choice(staff_user_ids) if staff_user_ids else 1,
          'completed', occupancy_rate, revenue,
          random.randint(3, 10), random.randint(3, 10), occupied,
          random.randint(0, 2), random.randint(0, 3),
          f"{audit_date} 23:55:00"))

print("   Added 30 night audits")

# ========== 8. COMPETITOR DATA ==========
print("\n[8/12] Seeding competitor_data...")
competitors = [
    ('The Grand Meridian', 37500),
    ('Harbor View Inn', 15000),
    ('City Center Suites', 18000),
    ('Coastal Resort & Spa', 31500)
]

room_types_for_comp = ['standard', 'deluxe', 'suite']

base_date = datetime.now() - timedelta(days=30)
for comp_name, base_rate in competitors:
    for i in range(30):
        data_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
        room_type = random.choice(room_types_for_comp)

        # Adjust rate based on room type
        type_multiplier = {'standard': 1.0, 'deluxe': 1.3, 'suite': 1.8}[room_type]
        rate = round(base_rate * type_multiplier * random.uniform(0.85, 1.25), 2)

        cursor.execute("""
            INSERT OR IGNORE INTO competitor_data
            (competitor_name, date, room_type, rate, availability,
             occupancy_estimate, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (comp_name, data_date, room_type, rate,
              random.randint(1, 15), random.uniform(55, 95), 'rate_shopper',
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

print("   Added 120 competitor data points (4 competitors x 30 days)")

# ========== 9. CHANNEL PERFORMANCE ==========
print("\n[9/12] Seeding channel_performance...")
channels = ['direct', 'booking.com', 'expedia', 'airbnb', 'corporate']

base_date = datetime.now() - timedelta(days=30)
for channel in channels:
    for i in range(30):
        perf_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')

        # Channel-specific booking patterns
        if channel == 'direct':
            bookings = random.randint(1, 4)
            commission_rate = 0
        elif channel == 'booking.com':
            bookings = random.randint(2, 6)
            commission_rate = 15
        elif channel == 'expedia':
            bookings = random.randint(1, 4)
            commission_rate = 18
        elif channel == 'airbnb':
            bookings = random.randint(0, 2)
            commission_rate = 14
        else:  # corporate
            bookings = random.randint(1, 3)
            commission_rate = 8

        revenue = round(bookings * random.uniform(16500, 33000), 2)
        commission_amount = round(revenue * commission_rate / 100, 2)
        net_revenue = revenue - commission_amount
        cancellations = random.randint(0, max(1, bookings // 3))
        cancellation_rate = round((cancellations / max(1, bookings)) * 100, 2)

        cursor.execute("""
            INSERT OR IGNORE INTO channel_performance
            (date, channel, bookings_count, revenue, commission_amount, commission_rate,
             net_revenue, cancellations_count, cancellation_rate, avg_booking_value,
             avg_lead_time, conversion_rate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (perf_date, channel, bookings, revenue, commission_amount, commission_rate,
              net_revenue, cancellations, cancellation_rate,
              round(revenue / max(1, bookings), 2),
              random.randint(3, 45), round(random.uniform(2, 8), 2),
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

print("   Added 150 channel performance records (5 channels x 30 days)")

# ========== 10. SENTIMENT TRENDS ==========
print("\n[10/12] Seeding sentiment_trends...")
categories = ['cleanliness', 'service', 'location', 'value', 'amenities', 'food']

base_date = datetime.now() - timedelta(days=60)
for i in range(60):
    trend_date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')

    for category in categories:
        # Generate realistic sentiment scores
        base_score = {'cleanliness': 4.3, 'service': 4.5, 'location': 4.7,
                     'value': 4.0, 'amenities': 4.2, 'food': 4.1}[category]
        score = round(base_score + random.uniform(-0.5, 0.3), 2)
        score = max(1, min(5, score))

        total = random.randint(5, 25)
        positive = int(total * random.uniform(0.5, 0.8))
        negative = int(total * random.uniform(0.05, 0.2))
        neutral = total - positive - negative

        cursor.execute("""
            INSERT OR IGNORE INTO sentiment_trends
            (date, category, positive_count, neutral_count, negative_count,
             total_count, sentiment_score, average_rating, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (trend_date, category, positive, neutral, negative,
              total, score, score, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

print("   Added 360 sentiment trend records (6 categories x 60 days)")

# ========== 11. LOYALTY TRANSACTIONS ==========
print("\n[11/12] Seeding loyalty_transactions...")
transaction_types = ['earn', 'redeem', 'bonus', 'expire', 'adjustment']
reasons = {
    'earn': ['Stay completion', 'Room charge', 'Dining spend', 'Spa service'],
    'redeem': ['Room upgrade', 'Free night', 'Spa credit', 'Dining credit'],
    'bonus': ['Birthday bonus', 'Anniversary bonus', 'Promotion', 'Tier upgrade'],
    'expire': ['Points expiration', 'Account dormancy'],
    'adjustment': ['Manual adjustment', 'Error correction', 'Goodwill gesture']
}

running_balance = {}

for i in range(60):
    guest_id = random.choice(guest_ids) if guest_ids else 1
    booking_id = random.choice(booking_ids) if booking_ids else None
    trans_type = random.choice(transaction_types)

    if trans_type == 'earn':
        points = random.randint(100, 1000)
    elif trans_type == 'redeem':
        points = -random.randint(500, 5000)
    elif trans_type == 'bonus':
        points = random.randint(200, 2000)
    elif trans_type == 'expire':
        points = -random.randint(100, 500)
    else:
        points = random.randint(-200, 200)

    # Track running balance per guest
    if guest_id not in running_balance:
        running_balance[guest_id] = 5000  # Start with base points
    running_balance[guest_id] += points
    if running_balance[guest_id] < 0:
        running_balance[guest_id] = 0

    created = random_datetime(90, 0)

    cursor.execute("""
        INSERT OR IGNORE INTO loyalty_transactions
        (guest_id, transaction_type, points, balance_after, reason,
         booking_id, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (guest_id, trans_type, points, running_balance[guest_id],
          random.choice(reasons[trans_type]),
          booking_id, f"Auto-generated {trans_type} transaction", created))

print("   Added 60 loyalty transactions")

# ========== 12. GUEST FEEDBACK ==========
print("\n[12/12] Seeding guest_feedback...")
feedback_types = ['complaint', 'suggestion', 'compliment', 'inquiry']
feedback_categories = ['room', 'service', 'dining', 'facilities', 'staff', 'general']
urgencies = ['low', 'medium', 'high', 'critical']
feedback_statuses = ['open', 'in_progress', 'resolved', 'closed']

feedback_subjects = [
    ("Room cleanliness issue", "complaint", "room"),
    ("Exceptional front desk service", "compliment", "staff"),
    ("Suggestion for breakfast menu", "suggestion", "dining"),
    ("Pool maintenance concern", "complaint", "facilities"),
    ("Inquiry about spa services", "inquiry", "facilities"),
    ("Thank you to housekeeping", "compliment", "service"),
    ("WiFi connectivity problems", "complaint", "room"),
    ("Request for extended checkout", "inquiry", "service"),
    ("Noise from adjacent room", "complaint", "room"),
    ("Parking lot suggestion", "suggestion", "facilities")
]

for i in range(30):
    guest_id = random.choice(guest_ids) if guest_ids else 1
    subject, f_type, category = random.choice(feedback_subjects)
    urgency = random.choice(urgencies)
    status = random.choice(feedback_statuses)
    priority = urgency
    created = random_datetime(60, 0)
    feedback_num = f"FB-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}"

    cursor.execute("""
        INSERT OR IGNORE INTO guest_feedback
        (feedback_number, guest_id, feedback_type, category, subject, description,
         urgency, priority, status, assigned_to, reported_via,
         follow_up_required, is_public, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (feedback_num, guest_id, f_type, category, subject,
          f"Detailed description of: {subject}",
          urgency, priority, status,
          random.choice(staff_user_ids) if staff_user_ids else None,
          random.choice(['phone', 'email', 'in_person', 'app', 'survey']),
          random.choice([True, False]), random.choice([True, False]),
          created, created))

print("   Added 30 guest feedback entries")

# Commit all changes
conn.commit()
conn.close()

print("\n" + "=" * 60)
print("DATA SEEDING COMPLETED SUCCESSFULLY!")
print("=" * 60)
print("\nSummary of seeded data:")
print("  - 40 housekeeping tasks")
print("  - 35 maintenance requests")
print("  - 50 reviews")
print("  - 90 days of daily metrics")
print("  - 45 staff tasks")
print("  - 40 runner deliveries")
print("  - 30 night audits")
print("  - 120 competitor data points")
print("  - 150 channel performance records")
print("  - 360 sentiment trends")
print("  - 60 loyalty transactions")
print("  - 30 guest feedback entries")
print("\nTotal: ~1,000 new records across 12 tables")
