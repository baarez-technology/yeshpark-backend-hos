"""
Test script to verify all Channel Manager API endpoints match requirements
"""
import asyncio
import httpx
import json
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional

# Configuration
BASE_URL = "http://localhost:8000"
TIMEOUT = 30.0

# Test token (replace with actual token)
TEST_TOKEN = None  # Will need to be set or obtained via login

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_test_header(test_name: str):
    print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}TEST: {test_name}{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")

def print_success(message: str):
    print(f"{Colors.GREEN}[PASS] {message}{Colors.RESET}")

def print_error(message: str):
    print(f"{Colors.RED}[FAIL] {message}{Colors.RESET}")

def print_info(message: str):
    print(f"{Colors.YELLOW}[INFO] {message}{Colors.RESET}")

async def test_endpoint(
    method: str,
    url: str,
    data: Optional[Dict[str, Any]] = None,
    description: str = "",
    expected_status: int = 200,
    token: Optional[str] = None
) -> tuple[bool, Optional[Dict[str, Any]], str]:
    """Test an API endpoint"""
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, json=data, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=data, headers=headers)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                return False, None, f"Unsupported method: {method}"
            
            success = response.status_code == expected_status
            
            try:
                result = response.json()
                if success:
                    return True, result, ""
                else:
                    error_msg = result.get("detail", result.get("message", "Unknown error"))
                    return False, result, f"Status {response.status_code}: {error_msg}"
            except:
                if success:
                    return True, {"text": response.text}, ""
                else:
                    return False, None, f"Status {response.status_code}: {response.text}"
                    
    except httpx.TimeoutException:
        return False, None, "Request timeout"
    except httpx.ConnectError:
        return False, None, f"Connection error - is the service running on {BASE_URL}?"
    except Exception as e:
        return False, None, f"Unexpected error: {str(e)}"

async def test_dashboard_stats():
    """Test Dashboard stats endpoint"""
    print_test_header("Dashboard - Get Channel Statistics")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/channel-manager/stats",
        description="Get channel stats",
        token=TEST_TOKEN
    )
    
    if success and response:
        data = response.get("data", {})
        
        # Check required fields
        required_fields = [
            "connectedOTAs", "disconnectedOTAs", "errorOTAs",
            "totalBookings", "totalRevenue", "mappedRoomTypes",
            "totalRoomTypes", "activeRestrictions", "rateParityIssues",
            "lastSync", "revenueTrend", "bookingsTrend",
            "channelPerformance", "avgCommission", "avgConversionRate",
            "revenueGrowth", "bookingsGrowth", "avgRate", "occupancyRate"
        ]
        
        all_present = True
        for field in required_fields:
            if field in data:
                print_success(f"Field '{field}' present")
            else:
                print_error(f"Field '{field}' missing")
                all_present = False
        
        if all_present:
            print_success("All required fields present in stats response")
            return True
        else:
            return False
    else:
        print_error(f"Stats endpoint failed: {error}")
        return False

async def test_ota_connections():
    """Test OTA Connections endpoints"""
    print_test_header("OTA Connections - Get All OTAs")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/channel-manager/otas",
        description="Get all OTAs",
        token=TEST_TOKEN
    )
    
    if success and response:
        data = response.get("data", {})
        items = data.get("items", [])
        
        if items:
            ota = items[0]
            required_fields = [
                "id", "name", "code", "status", "lastSync", "nextSync",
                "errorMessage", "credentials", "syncSettings", "stats", "color"
            ]
            
            all_present = True
            for field in required_fields:
                if field in ota:
                    print_success(f"OTA object has field '{field}'")
                else:
                    print_error(f"OTA object missing field '{field}'")
                    all_present = False
            
            # Check stats fields
            stats = ota.get("stats", {})
            stats_fields = ["totalBookings", "revenue", "avgRating", "commission"]
            for field in stats_fields:
                if field in stats:
                    print_success(f"Stats has field '{field}'")
                else:
                    print_error(f"Stats missing field '{field}'")
                    all_present = False
            
            return all_present
        else:
            print_info("No OTAs found (this is OK if none are connected)")
            return True
    else:
        print_error(f"OTAs endpoint failed: {error}")
        return False

async def test_room_mappings():
    """Test Room Mapping endpoints"""
    print_test_header("Room Mapping - Get All Mappings")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/channel-manager/room-mappings",
        description="Get room mappings",
        token=TEST_TOKEN
    )
    
    if success and response:
        data = response.get("data", {})
        items = data.get("items", [])
        
        if items:
            mapping = items[0]
            required_fields = [
                "id", "pmsRoomType", "pmsRoomTypeId", "pmsRoomCode",
                "basePrice", "inventory", "otaMappings"
            ]
            
            all_present = True
            for field in required_fields:
                if field in mapping:
                    print_success(f"Mapping has field '{field}'")
                else:
                    print_error(f"Mapping missing field '{field}'")
                    all_present = False
            
            # Check otaMappings structure
            ota_mappings = mapping.get("otaMappings", [])
            if ota_mappings:
                ota_map = ota_mappings[0]
                ota_fields = ["otaCode", "otaRoomType", "otaRoomId", "otaRoomCode", "status", "lastSync"]
                for field in ota_fields:
                    if field in ota_map:
                        print_success(f"OTA mapping has field '{field}'")
                    else:
                        print_error(f"OTA mapping missing field '{field}'")
                        all_present = False
            
            return all_present
        else:
            print_info("No room mappings found")
            return True
    else:
        print_error(f"Room mappings endpoint failed: {error}")
        return False

async def test_rate_sync():
    """Test Rate Sync endpoints"""
    print_test_header("Rate Sync - Get Rate Calendar")
    
    start_date = date.today().isoformat()
    end_date = (date.today() + timedelta(days=7)).isoformat()
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/channel-manager/rates/calendar?startDate={start_date}&endDate={end_date}",
        description="Get rate calendar",
        token=TEST_TOKEN
    )
    
    if success and response:
        data = response.get("data", {})
        calendar = data.get("calendar", {})
        
        if calendar:
            # Check first date entry
            first_date = list(calendar.keys())[0]
            first_entry = calendar[first_date]
            first_room = list(first_entry.keys())[0]
            room_data = first_entry[first_room]
            
            required_fields = ["date", "roomType", "rates", "otaRates", "availability", "stopSell", "cta", "ctd"]
            
            all_present = True
            for field in required_fields:
                if field in room_data:
                    print_success(f"Rate calendar entry has field '{field}'")
                else:
                    print_error(f"Rate calendar entry missing field '{field}'")
                    all_present = False
            
            return all_present
        else:
            print_info("No rate calendar data found")
            return True
    else:
        print_error(f"Rate calendar endpoint failed: {error}")
        return False

async def test_restrictions():
    """Test Restrictions endpoints"""
    print_test_header("Restrictions - Get All Restrictions")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/channel-manager/restrictions",
        description="Get restrictions",
        token=TEST_TOKEN
    )
    
    if success and response:
        data = response.get("data", {})
        items = data.get("items", [])
        
        if items:
            restriction = items[0]
            required_fields = [
                "id", "roomType", "otaCode", "dateRange", "restriction",
                "reason", "isActive", "createdAt"
            ]
            
            all_present = True
            for field in required_fields:
                if field in restriction:
                    print_success(f"Restriction has field '{field}'")
                else:
                    print_error(f"Restriction missing field '{field}'")
                    all_present = False
            
            # Check restriction object
            restriction_obj = restriction.get("restriction", {})
            restriction_fields = ["minStay", "maxStay", "cta", "ctd", "stopSell"]
            for field in restriction_fields:
                if field in restriction_obj:
                    print_success(f"Restriction object has field '{field}'")
                else:
                    print_error(f"Restriction object missing field '{field}'")
                    all_present = False
            
            return all_present
        else:
            print_info("No restrictions found")
            return True
    else:
        print_error(f"Restrictions endpoint failed: {error}")
        return False

async def test_promotions():
    """Test Promotions endpoints"""
    print_test_header("Promotions - Get All Promotions")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/channel-manager/promotions",
        description="Get promotions",
        token=TEST_TOKEN
    )
    
    if success and response:
        data = response.get("data", {})
        items = data.get("items", [])
        
        if items:
            promo = items[0]
            required_fields = [
                "id", "name", "description", "code", "discountType",
                "discountValue", "validFrom", "validTo", "otaCodes",
                "roomTypes", "minStay", "usageCount", "isActive",
                "createdAt", "updatedAt"
            ]
            
            all_present = True
            for field in required_fields:
                if field in promo:
                    print_success(f"Promotion has field '{field}'")
                else:
                    print_error(f"Promotion missing field '{field}'")
                    all_present = False
            
            return all_present
        else:
            print_info("No promotions found")
            return True
    else:
        print_error(f"Promotions endpoint failed: {error}")
        return False

async def test_sync_logs():
    """Test Sync Logs endpoints"""
    print_test_header("Sync Logs - Get Sync Logs")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/channel-manager/sync-logs?pageSize=5",
        description="Get sync logs",
        token=TEST_TOKEN
    )
    
    if success and response:
        data = response.get("data", {})
        items = data.get("items", [])
        
        # Check pagination fields
        pagination_fields = ["total", "page", "pageSize", "totalPages"]
        for field in pagination_fields:
            if field in data:
                print_success(f"Pagination field '{field}' present")
            else:
                print_error(f"Pagination field '{field}' missing")
        
        if items:
            log = items[0]
            required_fields = ["id", "timestamp", "otaCode", "otaName", "action", "status", "message", "details"]
            
            all_present = True
            for field in required_fields:
                if field in log:
                    print_success(f"Sync log has field '{field}'")
                else:
                    print_error(f"Sync log missing field '{field}'")
                    all_present = False
            
            # Check action type is one of the required values
            action = log.get("action", "")
            valid_actions = ["rate_update", "availability_update", "restriction_update", 
                           "promotion_sync", "booking_import", "connection", "bulk_sync"]
            if action in valid_actions or any(a in action.lower() for a in valid_actions):
                print_success(f"Action type '{action}' is valid")
            else:
                print_error(f"Action type '{action}' may not match requirements")
            
            return all_present
        else:
            print_info("No sync logs found")
            return True
    else:
        print_error(f"Sync logs endpoint failed: {error}")
        return False

async def test_bookings_by_source():
    """Test bookings endpoint with source filter"""
    print_test_header("Bookings - Get by Source")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{BASE_URL}/api/v1/bookings?source=CRS&limit=50",
        description="Get bookings by source",
        token=TEST_TOKEN
    )
    
    if success and response:
        # Check if response has data field or items directly
        if "data" in response:
            items = response["data"].get("items", [])
        else:
            items = response.get("items", [])
        
        if items:
            booking = items[0]
            required_fields = ["id", "guest", "guestName", "email", "checkIn", "checkOut", "roomType", "amount", "total", "source"]
            
            all_present = True
            for field in required_fields:
                if field in booking:
                    print_success(f"Booking has field '{field}'")
                else:
                    print_error(f"Booking missing field '{field}'")
                    all_present = False
            
            return all_present
        else:
            print_info("No bookings found for source CRS")
            return True
    else:
        print_error(f"Bookings endpoint failed: {error}")
        return False

async def main():
    """Run all tests"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}")
    print("CHANNEL MANAGER API REQUIREMENTS TEST SUITE")
    print("="*80)
    print(f"Base URL: {BASE_URL}")
    print(f"{'='*80}{Colors.RESET}\n")
    
    if not TEST_TOKEN:
        print_error("TEST_TOKEN not set. Some tests may fail due to authentication.")
        print_info("Set TEST_TOKEN or tests will run without authentication")
    
    results = []
    
    # Test all endpoints
    results.append(("Dashboard Stats", await test_dashboard_stats()))
    results.append(("OTA Connections", await test_ota_connections()))
    results.append(("Room Mappings", await test_room_mappings()))
    results.append(("Rate Sync", await test_rate_sync()))
    results.append(("Restrictions", await test_restrictions()))
    results.append(("Promotions", await test_promotions()))
    results.append(("Sync Logs", await test_sync_logs()))
    results.append(("Bookings by Source", await test_bookings_by_source()))
    
    # Print summary
    print(f"\n{Colors.BOLD}{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}{Colors.RESET}\n")
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        if result:
            print_success(f"{test_name}")
            passed += 1
        else:
            print_error(f"{test_name}")
            failed += 1
    
    print(f"\n{Colors.BOLD}Total Tests: {len(results)}")
    print(f"{Colors.GREEN}Passed: {passed}{Colors.RESET}")
    print(f"{Colors.RED}Failed: {failed}{Colors.RESET}")
    print(f"{'='*80}{Colors.RESET}\n")
    
    if failed == 0:
        print_success("All tests passed! ✓")
        return 0
    else:
        print_error(f"{failed} test(s) failed. Please review the errors above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
