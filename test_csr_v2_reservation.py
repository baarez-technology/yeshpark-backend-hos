"""
Test case for CSR (Customer Service Representative) creating a new reservation
using the v2 external application format.

This test validates the POST /api/v2/reservations endpoint in the dummy channel manager.
"""

import asyncio
import httpx
import json
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional
import sys
import io

# Fix Windows encoding issues
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# Configuration
DUMMY_CHANNEL_MANAGER_URL = "http://localhost:8001"
TIMEOUT = 30.0


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_test_header(test_name: str):
    """Print formatted test header"""
    print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}TEST: {test_name}{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")


def print_success(message: str):
    """Print success message"""
    print(f"{Colors.GREEN}[PASS] {message}{Colors.RESET}")


def print_error(message: str):
    """Print error message"""
    print(f"{Colors.RED}[FAIL] {message}{Colors.RESET}")


def print_info(message: str):
    """Print info message"""
    print(f"{Colors.YELLOW}[INFO] {message}{Colors.RESET}")


async def test_endpoint(
    method: str,
    url: str,
    data: Optional[Dict[str, Any]] = None,
    description: str = "",
    expected_status: int = 200
) -> tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Test an API endpoint
    
    Returns:
        (success: bool, response_data: dict, error_message: str)
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if method == "GET":
                response = await client.get(url)
            elif method == "POST":
                response = await client.post(url, json=data)
            elif method == "PUT":
                response = await client.put(url, json=data)
            elif method == "DELETE":
                response = await client.delete(url)
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
        return False, None, f"Connection error - is the service running on {url}?"
    except Exception as e:
        return False, None, f"Unexpected error: {str(e)}"


async def test_health_check() -> bool:
    """Test if dummy channel manager is running"""
    print_test_header("Health Check - Dummy Channel Manager")
    
    success, response, error = await test_endpoint(
        "GET",
        f"{DUMMY_CHANNEL_MANAGER_URL}/health",
        description="Health check"
    )
    
    if success:
        print_success("Dummy Channel Manager is running")
        if response:
            print_info(f"Response: {json.dumps(response, indent=2)}")
        return True
    else:
        print_error(f"Health check failed: {error}")
        print_error("Make sure the dummy channel manager is running on port 8001")
        return False


async def test_create_reservation_success() -> bool:
    """Test successful reservation creation with all fields"""
    print_test_header("Test 1: Create Reservation - Success Case (All Fields)")
    
    # Prepare reservation data
    arrival_date = (date.today() + timedelta(days=7)).isoformat()
    departure_date = (date.today() + timedelta(days=9)).isoformat()
    
    reservation_data = {
        "guest": {
            "first_name": "tripathi",
            "last_name": "prince",
            "email": "pkumar@gmail.com",
            "phone": "9999999999",
            "notes": "notes"
        },
        "rate_plan_id": 0,  # BAR (Best Available Rate)
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "adults": 2,
        "children": 0,  # Room ID 1 has max_occupancy=2, so only 2 adults allowed
        "special_requests": "Early check-in preferred, late checkout if possible",
        "group_code": "CSR-TEST-001",
        "promo_code": "SUMMER2026",
        "room_id": 1
        # hotel_id is optional - will be inferred from room_id
    }
    
    print_info(f"Request URL: POST {DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations")
    print_info(f"Request Body:\n{json.dumps(reservation_data, indent=2)}")
    
    success, response, error = await test_endpoint(
        "POST",
        f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
        data=reservation_data,
        expected_status=200
    )
    
    if success and response:
        print_success("Reservation created successfully!")
        print_info(f"Response:\n{json.dumps(response, indent=2)}")
        
        # Validate response structure
        if response.get("success") == True:
            print_success("Response has 'success: true'")
        else:
            print_error("Response missing 'success: true'")
            return False
            
        data = response.get("data")
        if data:
            print_success("Response contains 'data' field")
            
            # Check required fields in data
            required_fields = ["id", "confirmation_number", "status"]
            for field in required_fields:
                if field in data:
                    print_success(f"Response data contains '{field}': {data[field]}")
                else:
                    print_error(f"Response data missing required field: {field}")
                    return False
        else:
            print_error("Response missing 'data' field")
            return False
            
        return True
    else:
        print_error(f"Reservation creation failed: {error}")
        if response:
            print_error(f"Response: {json.dumps(response, indent=2)}")
        return False


async def test_create_reservation_minimal() -> bool:
    """Test reservation creation with minimal required fields"""
    print_test_header("Test 2: Create Reservation - Minimal Required Fields")
    
    arrival_date = (date.today() + timedelta(days=10)).isoformat()
    departure_date = (date.today() + timedelta(days=11)).isoformat()
    
    reservation_data = {
        "guest": {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane.smith@example.com",
            "phone": "555-9876"
        },
        "rate_plan_id": 1,  # NON_REFUNDABLE
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "adults": 1,
        "room_id": 1
    }
    
    print_info(f"Request Body (minimal fields):\n{json.dumps(reservation_data, indent=2)}")
    
    success, response, error = await test_endpoint(
        "POST",
        f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
        data=reservation_data,
        expected_status=200
    )
    
    if success:
        print_success("Minimal reservation created successfully!")
        return True
    else:
        print_error(f"Minimal reservation creation failed: {error}")
        return False


async def test_create_reservation_validation_errors() -> bool:
    """Test reservation creation with validation errors"""
    print_test_header("Test 3: Create Reservation - Validation Errors")
    
    all_passed = True
    
    # Test 3.1: Missing required guest field
    print_info("Test 3.1: Missing guest.first_name")
    reservation_data = {
        "guest": {
            "last_name": "Doe",
            "email": "test@example.com",
            "phone": "555-1234"
        },
        "rate_plan_id": 0,
        "arrival_date": (date.today() + timedelta(days=14)).isoformat(),
        "departure_date": (date.today() + timedelta(days=15)).isoformat(),
        "adults": 1,
        "room_id": 1
    }
    
    success, response, error = await test_endpoint(
        "POST",
        f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
        data=reservation_data,
        expected_status=422  # Validation error
    )
    
    if success:
        print_success("Validation error correctly returned for missing first_name")
    else:
        print_error(f"Expected validation error, got: {error}")
        all_passed = False
    
    # Test 3.2: Departure date before arrival date
    print_info("\nTest 3.2: Departure date before arrival date")
    reservation_data = {
        "guest": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone": "555-1234"
        },
        "rate_plan_id": 0,
        "arrival_date": (date.today() + timedelta(days=20)).isoformat(),
        "departure_date": (date.today() + timedelta(days=19)).isoformat(),  # Before arrival
        "adults": 1,
        "room_id": 1
    }
    
    success, response, error = await test_endpoint(
        "POST",
        f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
        data=reservation_data,
        expected_status=400  # Bad request
    )
    
    if success:
        print_success("Validation error correctly returned for invalid dates")
    else:
        print_error(f"Expected validation error, got: {error}")
        all_passed = False
    
    # Test 3.3: Invalid rate_plan_id
    print_info("\nTest 3.3: Invalid rate_plan_id (out of range)")
    reservation_data = {
        "guest": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone": "555-1234"
        },
        "rate_plan_id": 99,  # Invalid
        "arrival_date": (date.today() + timedelta(days=21)).isoformat(),
        "departure_date": (date.today() + timedelta(days=22)).isoformat(),
        "adults": 1,
        "room_id": 1
    }
    
    success, response, error = await test_endpoint(
        "POST",
        f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
        data=reservation_data,
        expected_status=400  # Bad request
    )
    
    if success:
        print_success("Validation error correctly returned for invalid rate_plan_id")
    else:
        print_error(f"Expected validation error, got: {error}")
        all_passed = False
    
    return all_passed


async def test_create_reservation_different_rate_plans() -> bool:
    """Test reservation creation with different rate plan IDs"""
    print_test_header("Test 4: Create Reservation - Different Rate Plans")
    
    rate_plans = [
        (0, "BAR (Best Available Rate)"),
        (1, "NON_REFUNDABLE"),
        (2, "CORPORATE"),
        (3, "PROMOTIONAL"),
        (4, "LONG_STAY")
    ]
    
    all_passed = True
    arrival_date = (date.today() + timedelta(days=30)).isoformat()
    departure_date = (date.today() + timedelta(days=31)).isoformat()
    
    for rate_plan_id, rate_plan_name in rate_plans:
        print_info(f"\nTesting rate plan {rate_plan_id} ({rate_plan_name})")
        
        reservation_data = {
            "guest": {
                "first_name": f"RatePlan{rate_plan_id}",
                "last_name": "Test",
                "email": f"rateplan{rate_plan_id}@example.com",
                "phone": "555-1234"
            },
            "rate_plan_id": rate_plan_id,
            "arrival_date": arrival_date,
            "departure_date": departure_date,
            "adults": 1,
            "room_id": 1
        }
        
        success, response, error = await test_endpoint(
            "POST",
            f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
            data=reservation_data,
            expected_status=200
        )
        
        if success:
            print_success(f"Rate plan {rate_plan_id} ({rate_plan_name}) - Reservation created")
        else:
            print_error(f"Rate plan {rate_plan_id} ({rate_plan_name}) - Failed: {error}")
            all_passed = False
        
        # Increment dates for next test
        arrival_date = (datetime.fromisoformat(arrival_date) + timedelta(days=1)).date().isoformat()
        departure_date = (datetime.fromisoformat(departure_date) + timedelta(days=1)).date().isoformat()
    
    return all_passed


async def test_create_reservation_with_children() -> bool:
    """Test reservation creation with children"""
    print_test_header("Test 5: Create Reservation - With Children")
    
    arrival_date = (date.today() + timedelta(days=40)).isoformat()
    departure_date = (date.today() + timedelta(days=42)).isoformat()
    
    reservation_data = {
        "guest": {
            "first_name": "Family",
            "last_name": "Traveler",
            "email": "family@example.com",
            "phone": "555-1234",
            "notes": "Traveling with children, need crib"
        },
        "rate_plan_id": 0,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "adults": 2,
        "children": 2,
        "special_requests": "Need crib for infant, high chair for toddler",
        "room_id": 2  # Room ID 2 has max_occupancy=4, can accommodate 2 adults + 2 children
    }
    
    print_info(f"Request Body:\n{json.dumps(reservation_data, indent=2)}")
    
    success, response, error = await test_endpoint(
        "POST",
        f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
        data=reservation_data,
        expected_status=200
    )
    
    if success:
        print_success("Family reservation with children created successfully!")
        if response and response.get("data"):
            print_info(f"Reservation ID: {response['data'].get('id')}")
            print_info(f"Confirmation Number: {response['data'].get('confirmation_number')}")
        return True
    else:
        print_error(f"Family reservation creation failed: {error}")
        return False


async def test_create_reservation_corporate_group() -> bool:
    """Test reservation creation with corporate group code"""
    print_test_header("Test 6: Create Reservation - Corporate Group")
    
    arrival_date = (date.today() + timedelta(days=50)).isoformat()
    departure_date = (date.today() + timedelta(days=52)).isoformat()
    
    reservation_data = {
        "guest": {
            "first_name": "Corporate",
            "last_name": "Guest",
            "email": "corporate@company.com",
            "phone": "555-1234",
            "notes": "Corporate account, frequent guest"
        },
        "rate_plan_id": 2,  # CORPORATE
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "adults": 1,
        "children": 0,
        "special_requests": "Quiet room, business center access needed",
        "group_code": "CORP-ACME-2026",
        "room_id": 1
    }
    
    print_info(f"Request Body:\n{json.dumps(reservation_data, indent=2)}")
    
    success, response, error = await test_endpoint(
        "POST",
        f"{DUMMY_CHANNEL_MANAGER_URL}/api/v2/reservations",
        data=reservation_data,
        expected_status=200
    )
    
    if success:
        print_success("Corporate reservation with group code created successfully!")
        return True
    else:
        print_error(f"Corporate reservation creation failed: {error}")
        return False


async def main():
    """Run all test cases"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}")
    print("CSR V2 RESERVATION CREATION TEST SUITE")
    print("="*80)
    print(f"Dummy Channel Manager URL: {DUMMY_CHANNEL_MANAGER_URL}")
    print(f"Endpoint: POST /api/v2/reservations")
    print(f"{'='*80}{Colors.RESET}\n")
    
    # Test results
    results = []
    
    # Test 0: Health check
    health_ok = await test_health_check()
    results.append(("Health Check", health_ok))
    
    if not health_ok:
        print_error("\nDummy Channel Manager is not running. Please start it first.")
        print_info("Run: cd dummy_channel_manager && python main.py")
        print_info("Or: uvicorn main:app --reload --host 0.0.0.0 --port 8001")
        sys.exit(1)
    
    # Test 1: Success case with all fields
    results.append(("Create Reservation - Success (All Fields)", await test_create_reservation_success()))
    
    # Test 2: Minimal required fields
    results.append(("Create Reservation - Minimal Fields", await test_create_reservation_minimal()))
    
    # Test 3: Validation errors
    results.append(("Create Reservation - Validation Errors", await test_create_reservation_validation_errors()))
    
    # Test 4: Different rate plans
    results.append(("Create Reservation - Different Rate Plans", await test_create_reservation_different_rate_plans()))
    
    # Test 5: With children
    results.append(("Create Reservation - With Children", await test_create_reservation_with_children()))
    
    # Test 6: Corporate group
    results.append(("Create Reservation - Corporate Group", await test_create_reservation_corporate_group()))
    
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
        print_success("All tests passed!")
        return 0
    else:
        print_error(f"{failed} test(s) failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
