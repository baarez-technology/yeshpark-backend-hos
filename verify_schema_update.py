"""
Schema Update Verification Script
Verifies that all V2.0 models are properly defined and can be imported
"""
import sys
from typing import List, Tuple


def verify_model_imports() -> Tuple[bool, List[str]]:
    """Verify all models can be imported"""
    errors = []
    
    print("=" * 80)
    print("VERIFYING MODEL IMPORTS")
    print("=" * 80)
    print()
    
    model_files = [
        ("app.models.base", ["TimestampedModel"]),
        ("app.models.user", ["User"]),
        ("app.models.reservations", ["Guest", "Reservation", "ReservationHistory", "ReservationNote", "Waitlist", "GroupBooking"]),
        ("app.models.inventory", ["RoomType", "Room", "RatePlan"]),
        ("app.models.operations", ["HousekeepingTask", "MaintenanceRequest", "Folio", "FolioLineItem", "Payment"]),
        ("app.models.staff", ["Staff", "StaffAttendance", "StaffPerformanceMetrics"]),
        ("app.models.runner", ["RunnerPickupRequest", "RunnerDelivery", "RunnerActivityLog"]),
        ("app.models.maintenance", ["EquipmentIssues", "MaintenanceParts", "Vendors"]),
        ("app.models.housekeeping", ["HousekeepingChecklistTemplates", "HousekeepingSupplies"]),
        ("app.models.crm", ["GuestStayHistory", "CRMGuestActivities", "LoyaltyTiers", "GuestFeedback"]),
        ("app.models.ai_system", ["AIIntents", "AIPrompts"]),
        ("app.models.reviews", ["Review", "OTAStats"]),
        ("app.models.bookings", ["RoomChanges", "BookingAddOns", "CorporateAccounts", "Packages"]),
        ("app.models.revenue", ["PricingAdjustments", "ChannelPerformance"]),
        ("app.models.configuration", ["SystemSettings", "EmailTemplates", "HotelSettings"]),
    ]
    
    total_models = 0
    imported_models = 0
    
    for module_name, models in model_files:
        try:
            module = __import__(module_name, fromlist=models)
            print(f"✓ {module_name}")
            
            for model in models:
                if hasattr(module, model):
                    imported_models += 1
                    print(f"  ✓ {model}")
                else:
                    errors.append(f"Model {model} not found in {module_name}")
                    print(f"  ✗ {model} - NOT FOUND")
                total_models += 1
                
        except ImportError as e:
            errors.append(f"Failed to import {module_name}: {str(e)}")
            print(f"✗ {module_name} - FAILED")
            total_models += len(models)
    
    print()
    print(f"Models imported: {imported_models}/{total_models}")
    print()
    
    return len(errors) == 0, errors


def verify_critical_fields() -> Tuple[bool, List[str]]:
    """Verify critical new fields exist in models"""
    errors = []
    
    print("=" * 80)
    print("VERIFYING CRITICAL NEW FIELDS")
    print("=" * 80)
    print()
    
    try:
        # Verify Staff model new fields
        from app.models.staff import Staff
        staff_fields = ['shift_start', 'shift_end', 'clocked_in', 'clock_in_time', 'supervisor_id', 'supervisor_name', 'specialty']
        
        print("Checking Staff model...")
        for field in staff_fields:
            if hasattr(Staff, field):
                print(f"  ✓ Staff.{field}")
            else:
                errors.append(f"Staff model missing field: {field}")
                print(f"  ✗ Staff.{field} - MISSING")
        
        # Verify Guest model new fields
        from app.models.reservations import Guest
        guest_fields = ['state', 'avatar', 'status', 'emotion', 'preferred_room_type', 'user_id', 'loyalty_points']
        
        print("\nChecking Guest model...")
        for field in guest_fields:
            if hasattr(Guest, field):
                print(f"  ✓ Guest.{field}")
            else:
                errors.append(f"Guest model missing field: {field}")
                print(f"  ✗ Guest.{field} - MISSING")
        
        # Verify Room model updates
        from app.models.inventory import Room, RoomType
        room_fields = ['room_type_id', 'condition', 'is_smoking', 'is_accessible']
        
        print("\nChecking Room model...")
        for field in room_fields:
            if hasattr(Room, field):
                print(f"  ✓ Room.{field}")
            else:
                errors.append(f"Room model missing field: {field}")
                print(f"  ✗ Room.{field} - MISSING")
        
        print("\nChecking RoomType model...")
        if RoomType:
            print(f"  ✓ RoomType model exists")
        else:
            errors.append("RoomType model not found")
            print(f"  ✗ RoomType model - NOT FOUND")
        
        # Verify User model updates
        from app.models.user import User
        user_fields = ['avatar', 'email_verified', 'last_login']
        
        print("\nChecking User model...")
        for field in user_fields:
            if hasattr(User, field):
                print(f"  ✓ User.{field}")
            else:
                errors.append(f"User model missing field: {field}")
                print(f"  ✗ User.{field} - MISSING")
        
    except Exception as e:
        errors.append(f"Error verifying fields: {str(e)}")
        print(f"\n✗ Error: {str(e)}")
    
    print()
    return len(errors) == 0, errors


def verify_new_models() -> Tuple[bool, List[str]]:
    """Verify all critical new models exist"""
    errors = []
    
    print("=" * 80)
    print("VERIFYING NEW CRITICAL MODELS")
    print("=" * 80)
    print()
    
    critical_models = [
        ("app.models.staff", "StaffAttendance", "Staff attendance tracking"),
        ("app.models.runner", "RunnerPickupRequest", "Runner pickup requests"),
        ("app.models.runner", "RunnerDelivery", "Runner deliveries"),
        ("app.models.runner", "RunnerActivityLog", "Runner activity log"),
        ("app.models.maintenance", "EquipmentIssues", "Equipment issues tracking"),
        ("app.models.maintenance", "Vendors", "Vendor management"),
        ("app.models.crm", "GuestStayHistory", "Guest stay history"),
        ("app.models.housekeeping", "HousekeepingChecklistTemplates", "Cleaning checklists"),
    ]
    
    for module_name, model_name, description in critical_models:
        try:
            module = __import__(module_name, fromlist=[model_name])
            if hasattr(module, model_name):
                print(f"✓ {model_name} ({description})")
            else:
                errors.append(f"Model {model_name} not found in {module_name}")
                print(f"✗ {model_name} - NOT FOUND")
        except ImportError as e:
            errors.append(f"Failed to import {module_name}: {str(e)}")
            print(f"✗ {model_name} - IMPORT FAILED")
    
    print()
    return len(errors) == 0, errors


def main():
    """Run all verification checks"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "SCHEMA UPDATE VERIFICATION" + " " * 32 + "║")
    print("║" + " " * 25 + "Version 2.0" + " " * 42 + "║")
    print("╚" + "=" * 78 + "╝")
    print("\n")
    
    all_passed = True
    all_errors = []
    
    # Test 1: Model Imports
    passed, errors = verify_model_imports()
    all_passed = all_passed and passed
    all_errors.extend(errors)
    
    # Test 2: Critical Fields
    passed, errors = verify_critical_fields()
    all_passed = all_passed and passed
    all_errors.extend(errors)
    
    # Test 3: New Models
    passed, errors = verify_new_models()
    all_passed = all_passed and passed
    all_errors.extend(errors)
    
    # Summary
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    print()
    
    if all_passed:
        print("✅ ALL CHECKS PASSED!")
        print()
        print("The backend models are fully updated and ready for migration.")
        print()
        print("Next steps:")
        print("  1. Backup your database")
        print("  2. Run: python migrate_to_v2_schema.py")
        print("  3. Start the application to create new tables")
        print("  4. Verify database with: python verify_database.py")
        print()
        return 0
    else:
        print("❌ SOME CHECKS FAILED")
        print()
        print(f"Total errors: {len(all_errors)}")
        print()
        print("Errors:")
        for i, error in enumerate(all_errors, 1):
            print(f"  {i}. {error}")
        print()
        print("Please fix these errors before proceeding with migration.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())

