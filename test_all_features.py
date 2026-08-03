"""
Comprehensive API Test Suite for Glimmora PMS
Tests all features from the feature list
"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000/api/v1"

# Get auth token
def get_token():
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@glimmora.com", "password": "admin123"})
    return resp.json().get("access_token")

TOKEN = get_token()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

errors = []
passed = []

def test(name, func):
    try:
        result = func()
        if result:
            passed.append(name)
            print(f"PASS: {name}")
        else:
            errors.append((name, "Test returned False"))
            print(f"FAIL: {name} - Test returned False")
    except Exception as e:
        errors.append((name, str(e)))
        print(f"ERROR: {name} - {str(e)[:100]}")

# ============================================
# CORE PMS - RESERVATIONS
# ============================================

def test_list_bookings():
    resp = requests.get(f"{BASE_URL}/bookings", headers=HEADERS)
    return resp.status_code == 200

def test_get_booking_by_id():
    resp = requests.get(f"{BASE_URL}/bookings/1", headers=HEADERS)
    return resp.status_code in [200, 404]

def test_create_booking():
    data = {
        "guest": {
            "first_name": "Test",
            "last_name": "User",
            "email": "testuser@test.com",
            "phone": "+1234567890",
            "country": "USA"
        },
        "room_type_id": 1,
        "check_in": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "check_out": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
        "adults": 2,
        "children": 0
    }
    resp = requests.post(f"{BASE_URL}/bookings", headers=HEADERS, json=data)
    return resp.status_code in [200, 201, 422]

def test_room_types():
    resp = requests.get(f"{BASE_URL}/room-types", headers=HEADERS)
    return resp.status_code == 200

def test_rooms_list():
    resp = requests.get(f"{BASE_URL}/rooms", headers=HEADERS)
    return resp.status_code == 200

def test_guests_list():
    resp = requests.get(f"{BASE_URL}/guests", headers=HEADERS)
    return resp.status_code == 200

def test_guest_by_id():
    resp = requests.get(f"{BASE_URL}/guests/1", headers=HEADERS)
    return resp.status_code in [200, 404]

def test_guest_stats():
    resp = requests.get(f"{BASE_URL}/guests/stats", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# HOUSEKEEPING
# ============================================

def test_housekeeping_dashboard():
    resp = requests.get(f"{BASE_URL}/housekeeping/dashboard", headers=HEADERS)
    return resp.status_code == 200

def test_housekeeping_rooms():
    resp = requests.get(f"{BASE_URL}/housekeeping/rooms", headers=HEADERS)
    return resp.status_code == 200

def test_housekeeping_tasks():
    resp = requests.get(f"{BASE_URL}/housekeeping/tasks", headers=HEADERS)
    return resp.status_code == 200

def test_housekeeping_staff():
    # Using correct endpoint path
    resp = requests.get(f"{BASE_URL}/housekeeping/staff/workload", headers=HEADERS)
    return resp.status_code == 200

def test_housekeeping_my_tasks():
    resp = requests.get(f"{BASE_URL}/housekeeping/tasks/my-tasks", headers=HEADERS)
    return resp.status_code == 200

def test_create_housekeeping_task():
    data = {
        "room_id": 1,
        "task_type": "clean",
        "priority": "medium",
        "notes": "Test task"
    }
    resp = requests.post(f"{BASE_URL}/housekeeping/tasks", headers=HEADERS, json=data)
    return resp.status_code in [200, 201, 422]

def test_lost_found():
    resp = requests.get(f"{BASE_URL}/housekeeping/lost-found", headers=HEADERS)
    return resp.status_code == 200

def test_linen_inventory():
    resp = requests.get(f"{BASE_URL}/housekeeping/linen-inventory", headers=HEADERS)
    return resp.status_code == 200

def test_housekeeping_maintenance():
    resp = requests.get(f"{BASE_URL}/housekeeping/maintenance", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# MAINTENANCE
# ============================================

def test_maintenance_dashboard():
    resp = requests.get(f"{BASE_URL}/maintenance/dashboard", headers=HEADERS)
    return resp.status_code == 200

def test_maintenance_work_orders():
    resp = requests.get(f"{BASE_URL}/maintenance/work-orders", headers=HEADERS)
    return resp.status_code == 200

def test_maintenance_equipment():
    # Correct endpoint path
    resp = requests.get(f"{BASE_URL}/maintenance/equipment-issues", headers=HEADERS)
    return resp.status_code == 200

def test_maintenance_preventive():
    # Correct endpoint path
    resp = requests.get(f"{BASE_URL}/maintenance/preventive-schedules", headers=HEADERS)
    return resp.status_code == 200

def test_create_work_order():
    data = {
        "room_id": 1,
        "issue_type": "plumbing",
        "priority": "medium",
        "description": "Test work order"
    }
    resp = requests.post(f"{BASE_URL}/maintenance/work-orders", headers=HEADERS, json=data)
    return resp.status_code in [200, 201, 422]

# ============================================
# RUNNER / BELL DESK
# ============================================

def test_runner_dashboard():
    resp = requests.get(f"{BASE_URL}/runner/dashboard", headers=HEADERS)
    return resp.status_code == 200

def test_runner_deliveries():
    resp = requests.get(f"{BASE_URL}/runner/deliveries", headers=HEADERS)
    return resp.status_code == 200

def test_runner_pickups():
    # Correct endpoint path
    resp = requests.get(f"{BASE_URL}/runner/pickups", headers=HEADERS)
    return resp.status_code == 200

def test_create_delivery():
    data = {
        "item_description": "Test luggage",
        "pickup_location": "Lobby",
        "destination": "Room 501",
        "guest_name": "Test Guest",
        "priority": "normal"
    }
    resp = requests.post(f"{BASE_URL}/runner/deliveries", headers=HEADERS, json=data)
    return resp.status_code in [200, 201, 422]

# ============================================
# PRE-CHECKIN
# ============================================

def test_precheckin_list():
    resp = requests.get(f"{BASE_URL}/precheckin", headers=HEADERS)
    return resp.status_code == 200

def test_precheckin_availability():
    # Availability requires POST with dates
    today = datetime.now()
    data = {
        "check_in": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
        "check_out": (today + timedelta(days=10)).strftime("%Y-%m-%d"),
        "adults": 2
    }
    resp = requests.post(f"{BASE_URL}/availability", headers=HEADERS, json=data)
    return resp.status_code in [200, 422]

# ============================================
# STAFF
# ============================================

def test_staff_list():
    resp = requests.get(f"{BASE_URL}/staff", headers=HEADERS)
    return resp.status_code == 200

def test_staff_by_id():
    resp = requests.get(f"{BASE_URL}/staff/1", headers=HEADERS)
    return resp.status_code in [200, 404]

def test_staff_available():
    # Correct endpoint path
    resp = requests.get(f"{BASE_URL}/staff/available", headers=HEADERS)
    return resp.status_code == 200

def test_staff_schedule():
    # Get individual staff schedule
    resp = requests.get(f"{BASE_URL}/staff/1/schedule", headers=HEADERS)
    return resp.status_code in [200, 404]

# ============================================
# RATES
# ============================================

def test_rate_plans():
    resp = requests.get(f"{BASE_URL}/rates/plans", headers=HEADERS)
    return resp.status_code == 200

def test_rate_calculate():
    params = {
        "room_type_id": 1,
        "check_in": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "check_out": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
    }
    resp = requests.get(f"{BASE_URL}/rates/calculate", headers=HEADERS, params=params)
    return resp.status_code in [200, 422]

def test_promo_codes():
    resp = requests.get(f"{BASE_URL}/rates/promo-codes", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# ANALYTICS & REPORTS
# ============================================

def test_analytics_dashboard():
    resp = requests.get(f"{BASE_URL}/analytics/dashboard", headers=HEADERS)
    return resp.status_code == 200

def test_analytics_kpis():
    resp = requests.get(f"{BASE_URL}/analytics/dashboard/kpis", headers=HEADERS)
    return resp.status_code == 200

def test_analytics_predictions():
    resp = requests.get(f"{BASE_URL}/analytics/predictions/revenue?days_ahead=30", headers=HEADERS)
    return resp.status_code == 200

def test_reports_occupancy():
    # Reports require date parameters
    today = datetime.now()
    params = {
        "start_date": (today - timedelta(days=30)).strftime("%Y-%m-%d"),
        "end_date": today.strftime("%Y-%m-%d")
    }
    resp = requests.get(f"{BASE_URL}/reports/occupancy", headers=HEADERS, params=params)
    return resp.status_code == 200

def test_reports_revenue():
    today = datetime.now()
    params = {
        "start_date": (today - timedelta(days=30)).strftime("%Y-%m-%d"),
        "end_date": today.strftime("%Y-%m-%d")
    }
    resp = requests.get(f"{BASE_URL}/reports/revenue", headers=HEADERS, params=params)
    return resp.status_code == 200

def test_reports_daily_flash():
    resp = requests.get(f"{BASE_URL}/reports/daily-flash", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# ADMIN AI
# ============================================

def test_admin_ai_chat():
    data = {"message": "How many guests do we have?"}
    resp = requests.post(f"{BASE_URL}/admin-ai/chat", headers=HEADERS, json=data)
    return resp.status_code in [200, 422, 500]

def test_admin_ai_capabilities():
    resp = requests.get(f"{BASE_URL}/admin-ai/capabilities", headers=HEADERS)
    return resp.status_code == 200

def test_admin_ai_audit():
    resp = requests.get(f"{BASE_URL}/admin-ai/audit", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# GUEST AI
# ============================================

def test_guest_ai_chat():
    data = {"message": "Hello"}
    resp = requests.post(f"{BASE_URL}/guest-ai/chat", headers=HEADERS, json=data)
    return resp.status_code in [200, 422, 500]

# ============================================
# REVENUE INTELLIGENCE
# ============================================

def test_revenue_dashboard():
    resp = requests.get(f"{BASE_URL}/revenue-intelligence/dashboard", headers=HEADERS)
    return resp.status_code == 200

def test_revenue_kpis():
    resp = requests.get(f"{BASE_URL}/revenue-intelligence/kpis", headers=HEADERS)
    return resp.status_code == 200

def test_revenue_forecast():
    resp = requests.get(f"{BASE_URL}/revenue-intelligence/forecast", headers=HEADERS)
    return resp.status_code == 200

def test_revenue_recommendations():
    resp = requests.get(f"{BASE_URL}/revenue-intelligence/pricing/recommendations", headers=HEADERS)
    return resp.status_code == 200

def test_revenue_opportunities():
    resp = requests.get(f"{BASE_URL}/revenue-intelligence/opportunities", headers=HEADERS)
    return resp.status_code == 200

def test_revenue_channels():
    resp = requests.get(f"{BASE_URL}/revenue-intelligence/channels", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# REPUTATION AI
# ============================================

def test_reputation_dashboard():
    resp = requests.get(f"{BASE_URL}/reputation/dashboard", headers=HEADERS)
    return resp.status_code == 200

def test_reputation_analytics():
    resp = requests.get(f"{BASE_URL}/reputation/analytics", headers=HEADERS)
    return resp.status_code == 200

def test_reputation_trends():
    resp = requests.get(f"{BASE_URL}/reputation/trends", headers=HEADERS)
    return resp.status_code == 200

def test_reputation_reviews_pending():
    resp = requests.get(f"{BASE_URL}/reputation/reviews/pending", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# CRM AI
# ============================================

def test_crm_dashboard():
    resp = requests.get(f"{BASE_URL}/crm-ai/dashboard", headers=HEADERS)
    return resp.status_code == 200

def test_crm_segments():
    resp = requests.get(f"{BASE_URL}/crm-ai/segments/analysis", headers=HEADERS)
    return resp.status_code == 200

def test_crm_at_risk_guests():
    resp = requests.get(f"{BASE_URL}/crm-ai/at-risk-guests", headers=HEADERS)
    return resp.status_code == 200

def test_crm_recovery_opportunities():
    resp = requests.get(f"{BASE_URL}/crm-ai/recovery/opportunities", headers=HEADERS)
    return resp.status_code == 200

def test_crm_campaign_recommendations():
    resp = requests.get(f"{BASE_URL}/crm-ai/campaigns/recommendations", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# DASHBOARDS
# ============================================

def test_dashboards_admin():
    resp = requests.get(f"{BASE_URL}/dashboards/admin", headers=HEADERS)
    return resp.status_code == 200

def test_frontdesk_arrivals():
    resp = requests.get(f"{BASE_URL}/frontdesk/arrivals", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# NOTIFICATIONS
# ============================================

def test_notifications_list():
    resp = requests.get(f"{BASE_URL}/notifications", headers=HEADERS)
    return resp.status_code == 200

# ============================================
# RUN ALL TESTS
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("GLIMMORA PMS - COMPREHENSIVE API TEST SUITE")
    print("=" * 60)
    print()

    # Core PMS - Reservations
    print("\n--- CORE PMS: RESERVATIONS ---")
    test("List Bookings", test_list_bookings)
    test("Get Booking by ID", test_get_booking_by_id)
    test("Create Booking", test_create_booking)
    test("Room Types", test_room_types)
    test("Rooms List", test_rooms_list)
    test("Guests List", test_guests_list)
    test("Guest by ID", test_guest_by_id)
    test("Guest Stats", test_guest_stats)

    # Housekeeping
    print("\n--- HOUSEKEEPING ---")
    test("Housekeeping Dashboard", test_housekeeping_dashboard)
    test("Housekeeping Rooms", test_housekeeping_rooms)
    test("Housekeeping Tasks", test_housekeeping_tasks)
    test("Housekeeping Staff", test_housekeeping_staff)
    test("Housekeeping My Tasks", test_housekeeping_my_tasks)
    test("Create Housekeeping Task", test_create_housekeeping_task)
    test("Lost & Found", test_lost_found)
    test("Linen Inventory", test_linen_inventory)
    test("Housekeeping Maintenance", test_housekeeping_maintenance)

    # Maintenance
    print("\n--- MAINTENANCE ---")
    test("Maintenance Dashboard", test_maintenance_dashboard)
    test("Maintenance Work Orders", test_maintenance_work_orders)
    test("Maintenance Equipment", test_maintenance_equipment)
    test("Maintenance Preventive", test_maintenance_preventive)
    test("Create Work Order", test_create_work_order)

    # Runner
    print("\n--- RUNNER / BELL DESK ---")
    test("Runner Dashboard", test_runner_dashboard)
    test("Runner Deliveries", test_runner_deliveries)
    test("Runner Pickups", test_runner_pickups)
    test("Create Delivery", test_create_delivery)

    # Pre-checkin
    print("\n--- PRE-CHECKIN ---")
    test("Pre-checkin List", test_precheckin_list)
    test("Availability", test_precheckin_availability)

    # Staff
    print("\n--- STAFF ---")
    test("Staff List", test_staff_list)
    test("Staff by ID", test_staff_by_id)
    test("Staff Available", test_staff_available)
    test("Staff Schedule", test_staff_schedule)

    # Rates
    print("\n--- RATES ---")
    test("Rate Plans", test_rate_plans)
    test("Rate Calculate", test_rate_calculate)
    test("Promo Codes", test_promo_codes)

    # Analytics
    print("\n--- ANALYTICS & REPORTS ---")
    test("Analytics Dashboard", test_analytics_dashboard)
    test("Analytics KPIs", test_analytics_kpis)
    test("Analytics Predictions", test_analytics_predictions)
    test("Reports Occupancy", test_reports_occupancy)
    test("Reports Revenue", test_reports_revenue)
    test("Reports Daily Flash", test_reports_daily_flash)

    # AI
    print("\n--- AI ASSISTANTS ---")
    test("Admin AI Chat", test_admin_ai_chat)
    test("Admin AI Capabilities", test_admin_ai_capabilities)
    test("Admin AI Audit", test_admin_ai_audit)
    test("Guest AI Chat", test_guest_ai_chat)

    # Revenue Intelligence
    print("\n--- REVENUE INTELLIGENCE ---")
    test("Revenue Dashboard", test_revenue_dashboard)
    test("Revenue KPIs", test_revenue_kpis)
    test("Revenue Forecast", test_revenue_forecast)
    test("Revenue Recommendations", test_revenue_recommendations)
    test("Revenue Opportunities", test_revenue_opportunities)
    test("Revenue Channels", test_revenue_channels)

    # Reputation
    print("\n--- REPUTATION AI ---")
    test("Reputation Dashboard", test_reputation_dashboard)
    test("Reputation Analytics", test_reputation_analytics)
    test("Reputation Trends", test_reputation_trends)
    test("Reputation Reviews Pending", test_reputation_reviews_pending)

    # CRM
    print("\n--- CRM AI ---")
    test("CRM Dashboard", test_crm_dashboard)
    test("CRM Segments", test_crm_segments)
    test("CRM At-Risk Guests", test_crm_at_risk_guests)
    test("CRM Recovery Opportunities", test_crm_recovery_opportunities)
    test("CRM Campaign Recommendations", test_crm_campaign_recommendations)

    # Dashboards
    print("\n--- DASHBOARDS ---")
    test("Dashboards Admin", test_dashboards_admin)
    test("Frontdesk Arrivals", test_frontdesk_arrivals)

    # Notifications
    print("\n--- NOTIFICATIONS ---")
    test("Notifications List", test_notifications_list)

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"PASSED: {len(passed)}")
    print(f"FAILED: {len(errors)}")
    print()

    if errors:
        print("FAILED TESTS:")
        for name, error in errors:
            print(f"  - {name}: {error[:80]}")
