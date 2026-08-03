from datetime import datetime, date
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
from app.models.base import TimestampedModel


class HousekeepingTask(SQLModel, table=True):
    """Room cleaning and housekeeping tasks"""
    __tablename__ = "housekeeping_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="rooms.id", index=True)
    task_type: str = Field(default="cleaning", index=True)  # cleaning, inspection, turndown, deep_clean
    priority: str = Field(default="normal", index=True)  # low, normal, high, urgent
    status: str = Field(default="pending", index=True)  # pending, in_progress, completed, cancelled
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id", index=True)
    checklist_template_id: Optional[int] = Field(default=None, foreign_key="housekeeping_checklist_templates.id")
    scheduled_for: Optional[datetime] = Field(default=None, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_duration: Optional[int] = None  # minutes
    actual_duration: Optional[int] = None  # minutes
    checklist: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    notes: Optional[str] = None
    quality_score: Optional[int] = None  # 1-5
    inspection_passed: Optional[bool] = None
    created_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    # Accept/Decline workflow fields
    acceptance_status: Optional[str] = Field(default=None, index=True)  # pending_acceptance, accepted, declined
    decline_reason: Optional[str] = None
    accepted_at: Optional[datetime] = None
    declined_at: Optional[datetime] = None
    # Force-assign fields
    force_assigned: bool = Field(default=False)  # True if admin overrode availability
    force_assign_reason: Optional[str] = None
    force_assigned_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MaintenanceRequest(SQLModel, table=True):
    """Maintenance and repair work orders"""
    __tablename__ = "maintenancerequest"

    id: Optional[int] = Field(default=None, primary_key=True)
    work_order_id: str = Field(unique=True, index=True)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)
    room_number: Optional[str] = Field(default=None, index=True)  # For quick lookup without join
    location: Optional[str] = None
    title: Optional[str] = None  # Short title for the work order
    category: str = Field(nullable=False, index=True)  # electrical, plumbing, hvac, carpentry, appliance, general
    issue_type: Optional[str] = Field(default=None, index=True)  # Alias for category in API
    priority: str = Field(default="medium", index=True)  # low, medium, high, emergency
    issue: str = Field(nullable=False)
    description: Optional[str] = None
    status: str = Field(default="open", index=True)  # open, assigned, in_progress, on_hold, completed, cancelled
    severity: Optional[str] = None
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id", index=True)
    reported_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    reported_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    scheduled_for: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    estimated_duration: Optional[int] = None  # minutes
    actual_duration: Optional[int] = None  # minutes
    is_out_of_order: bool = Field(default=False)
    requires_parts: bool = Field(default=False)
    parts_ordered: bool = Field(default=False)
    vendor_id: Optional[int] = Field(default=None, foreign_key="vendors.id", index=True)
    notes: Optional[str] = None
    resolution_notes: Optional[str] = None
    attachments: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    # Preventive maintenance fields
    is_preventive: bool = Field(default=False, index=True)
    preventive_schedule_id: Optional[int] = Field(default=None, index=True)
    scheduled_date: Optional[date_type] = Field(default=None, index=True)
    # Room block integration - auto-create block when OOO
    room_block_id: Optional[int] = Field(default=None, index=True)  # Link to RoomBlock (no FK to avoid circular)
    estimated_completion: Optional[datetime] = Field(default=None, index=True)  # Expected completion for OOO
    ooo_category: Optional[str] = None  # plumbing, electrical, hvac, renovation, damage, inspection
    # Accept/Decline workflow fields
    acceptance_status: Optional[str] = Field(default=None, index=True)  # pending_acceptance, accepted, declined
    decline_reason: Optional[str] = None
    accepted_at: Optional[datetime] = None
    declined_at: Optional[datetime] = None
    # Force-assign fields
    force_assigned: bool = Field(default=False)  # True if admin overrode availability
    force_assign_reason: Optional[str] = None
    force_assigned_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LostFound(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    item_description: str
    location_found: Optional[str] = None
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id")
    found_by: Optional[int] = Field(default=None, foreign_key="users.id")
    found_date: date_type = Field(default_factory=date.today, index=True)
    status: str = Field(default="stored", index=True)  # stored, claimed, disposed
    claimed_by_guest_id: Optional[int] = Field(default=None, foreign_key="guests.id")
    claimed_at: Optional[datetime] = None
    storage_location: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LinenInventory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    item_type: str = Field(index=True)  # sheets, towels, pillowcases, etc.
    quantity: int = 0
    location: Optional[str] = None  # room number, laundry, storage
    status: str = Field(default="available", index=True)  # available, in_use, damaged, in_laundry
    last_updated: datetime = Field(default_factory=datetime.utcnow, index=True)
    notes: Optional[str] = None


class Folio(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id", index=True)
    reservation_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)
    folio_number: str = Field(index=True, unique=True)
    window_label: str = Field(default="A")  # A, B, C, etc. for multi-window support
    folio_type: str = Field(default="guest")  # guest, incidental, company
    total_charges: float = 0.0
    total_payments: float = 0.0
    balance: float = 0.0
    currency: str = "INR"
    status: str = Field(default="open", index=True)  # open, closed, transferred
    invoice_number: Optional[str] = Field(default=None, index=True)  # Auto-generated on settle (GST invoice)
    is_settled: bool = Field(default=False)  # True once settled — blocks further edits
    print_count: int = Field(default=0)  # 0=not printed, 1=Original, 2+=Copy of Folio
    closed_at: Optional[datetime] = None
    closed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FolioLineItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    folio_id: int = Field(foreign_key="folio.id", index=True)
    item_type: str = Field(index=True)  # room_charge, service, tax, discount, payment, refund, minibar, spa, parking, restaurant, phone, laundry, late_checkout, damage, newspaper, misc
    transaction_code: Optional[str] = Field(default=None, index=True)  # Opera-style numeric code (e.g., "1000" for Room Charge)
    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    amount: float
    posted_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    posted_by: Optional[int] = Field(default=None, foreign_key="users.id")
    reference_id: Optional[int] = None  # Can reference reservation, payment, etc.
    notes: Optional[str] = None
    is_voided: bool = Field(default=False)
    voided_by: Optional[int] = Field(default=None, foreign_key="users.id")
    voided_at: Optional[datetime] = None
    original_line_item_id: Optional[int] = None  # Links adjustments/splits to the original item
    source_folio_id: Optional[int] = None  # For transfers: which folio it came from
    source_booking_id: Optional[int] = None  # For cross-booking transfers: original booking
    tax_category_id: Optional[int] = Field(default=None, foreign_key="taxcategory.id")
    tax_rate_pct: Optional[float] = None  # Total tax rate applied
    tax_amount: Optional[float] = None  # Total tax amount
    tax_component_1_name: Optional[str] = None  # "CGST"
    tax_component_1_pct: Optional[float] = None  # 9.0
    tax_component_1_amount: Optional[float] = None  # Calculated CGST amount
    tax_component_2_name: Optional[str] = None  # "SGST"
    tax_component_2_pct: Optional[float] = None  # 9.0
    tax_component_2_amount: Optional[float] = None  # Calculated SGST amount
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Payment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    folio_id: int = Field(foreign_key="folio.id", index=True)
    amount: float
    currency: str = "INR"
    method: str = Field(index=True)  # card, cash, bank_transfer, upi, neft, net_banking, voucher, comp
    payment_type: str = Field(default="deposit")  # deposit, full_payment, partial, refund
    transaction_id: Optional[str] = Field(default=None, index=True)
    authorization_code: Optional[str] = None
    card_last4: Optional[str] = None
    card_brand: Optional[str] = None
    upi_id: Optional[str] = None  # UPI VPA (e.g., name@upi) for UPI payments
    status: str = Field(default="captured", index=True)  # captured, authorized, refunded, voided, failed
    processed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    processed_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    refunded_at: Optional[datetime] = None
    refunded_by: Optional[int] = Field(default=None, foreign_key="users.id")
    refund_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChargeRoutingRule(SQLModel, table=True):
    """Auto-route charges to specific folios based on category"""
    __tablename__ = "charge_routing_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key="bookings.id", index=True)
    charge_category: str = Field(index=True)  # room_charge, minibar, spa, restaurant, parking, phone, laundry, etc.
    target_folio_id: int = Field(foreign_key="folio.id")
    payment_method: Optional[str] = None  # If set, auto-pay with this method
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuthorizationHold(SQLModel, table=True):
    """Pre-authorization / card hold placed at check-in.
    Amount = incidental_hold_pct × rate_per_night × nights.
    Released automatically at checkout or manually by staff."""
    __tablename__ = "authorizationhold"

    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key="bookings.id", index=True)
    folio_id: Optional[int] = Field(default=None, foreign_key="folio.id")
    hold_amount: float = 0.0
    card_last4: Optional[str] = None
    card_brand: Optional[str] = None
    authorization_code: Optional[str] = None
    status: str = Field(default="authorized", index=True)  # authorized, captured, released, expired
    authorized_at: datetime = Field(default_factory=datetime.utcnow)
    authorized_by: Optional[int] = Field(default=None, foreign_key="users.id")
    released_at: Optional[datetime] = None
    released_by: Optional[int] = Field(default=None, foreign_key="users.id")
    release_reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class KeyCard(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reservation_id: int = Field(foreign_key="reservation.id", index=True)
    card_number: str = Field(index=True, unique=True)
    room_id: int = Field(foreign_key="rooms.id")
    issued_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    issued_by: Optional[int] = Field(default=None, foreign_key="users.id")
    valid_from: datetime
    valid_until: datetime
    status: str = Field(default="active", index=True)  # active, deactivated, lost, expired
    deactivated_at: Optional[datetime] = None
    deactivated_by: Optional[int] = Field(default=None, foreign_key="users.id")
    deactivation_reason: Optional[str] = None
    notes: Optional[str] = None


class DigitalKey(SQLModel, table=True):
    """Digital room key with QR code for mobile check-in"""
    __tablename__ = "digital_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    key_code: str = Field(index=True, unique=True)  # Unique key identifier (e.g., DK-XXXXXX)
    booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id", index=True)
    reservation_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)
    precheckin_id: Optional[int] = Field(default=None, foreign_key="precheckin.id", index=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    room_id: int = Field(foreign_key="rooms.id", index=True)
    room_number: str = Field(index=True)  # Denormalized for quick lookup

    # QR Code data
    qr_data: str  # The data encoded in QR code (encrypted payload)
    qr_image_base64: Optional[str] = None  # Base64 encoded QR code image

    # Validity period
    valid_from: datetime = Field(index=True)
    valid_until: datetime = Field(index=True)
    check_in_date: date_type = Field(index=True)
    check_out_date: date_type = Field(index=True)

    # Status
    status: str = Field(default="active", index=True)  # active, used, expired, revoked
    activated_at: Optional[datetime] = None

    # Security
    secret_hash: str  # Hashed secret for validation
    scan_count: int = Field(default=0)
    last_scanned_at: Optional[datetime] = None
    last_scanned_by: Optional[int] = Field(default=None, foreign_key="staff.id")

    # Email delivery
    email_sent: bool = Field(default=False)
    email_sent_at: Optional[datetime] = None
    email_address: Optional[str] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    revoke_reason: Optional[str] = None


class DigitalKeyScan(SQLModel, table=True):
    """Scan history for digital keys - tracks all validation attempts"""
    __tablename__ = "digital_key_scans"

    id: Optional[int] = Field(default=None, primary_key=True)
    digital_key_id: int = Field(foreign_key="digital_keys.id", index=True)
    scanned_by: int = Field(foreign_key="staff.id", index=True)
    scanned_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Scan result
    is_valid: bool = Field(index=True)
    validation_result: str  # valid, expired, revoked, wrong_room, wrong_date, invalid_code

    # Context
    scan_location: Optional[str] = None  # room_door, housekeeping, front_desk
    room_number: Optional[str] = None
    ip_address: Optional[str] = None
    device_info: Optional[str] = None

    # Additional info
    notes: Optional[str] = None


class GuestCommunication(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reservation_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    communication_type: str = Field(index=True)  # email, sms, phone, in_person, chat
    direction: str = Field(index=True)  # inbound, outbound
    subject: Optional[str] = None
    message: str
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    status: str = Field(default="sent", index=True)  # sent, delivered, read, failed
    sent_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class NightAudit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    audit_date: date_type = Field(index=True, unique=True)
    run_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    run_by: Optional[int] = Field(default=None, foreign_key="users.id")
    status: str = Field(default="running", index=True)  # running, completed, failed
    occupancy_rate: Optional[float] = None
    revenue: Optional[float] = None
    arrivals: int = 0
    departures: int = 0
    in_house: int = 0
    no_shows: int = 0
    walk_ins: int = 0
    room_charges_posted: int = 0
    room_charge_revenue: float = 0.0
    auto_checkouts: int = 0
    # --- Opera PMS statistics ---
    adr: Optional[float] = None               # Average Daily Rate
    revpar: Optional[float] = None             # Revenue Per Available Room
    total_room_revenue: float = 0.0
    total_fnb_revenue: float = 0.0
    total_other_revenue: float = 0.0
    total_tax_collected: float = 0.0
    total_payments_received: float = 0.0
    rooms_returned_from_ooo: int = 0
    expired_auth_holds_count: int = 0
    ar_postings_aged: int = 0
    rooms_set_dirty: int = 0                   # occupied rooms → dirty
    procedure_log: Optional[str] = None        # JSON: step-by-step execution log
    errors: Optional[str] = None
    notes: Optional[str] = None
    completed_at: Optional[datetime] = None


class ShiftHandover(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shift_date: date_type = Field(index=True)
    shift_type: str = Field(index=True)  # morning, afternoon, night
    handed_over_by: int = Field(foreign_key="users.id")
    handed_over_to: int = Field(foreign_key="users.id")
    handover_time: datetime = Field(default_factory=datetime.utcnow, index=True)
    arrivals_count: int = 0
    departures_count: int = 0
    in_house_count: int = 0
    issues: Optional[str] = None
    notes: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HotelConfig(SQLModel, table=True):
    """Singleton hotel configuration — one row per property.
    Controls business date (only advances via night audit), timezone,
    currency, and incidental hold percentage for pre-auth."""
    __tablename__ = "hotelconfig"

    id: Optional[int] = Field(default=None, primary_key=True)
    business_date: date_type = Field(default_factory=date.today, index=True)
    night_audit_cutoff: str = Field(default="03:00")  # HH:MM — default 3 AM
    timezone: str = Field(default="Asia/Kolkata")
    currency: str = Field(default="INR")
    incidental_hold_pct: float = Field(default=20.0)  # % of room charges to pre-auth
    digital_key_activation_minutes: int = Field(default=60)  # Minutes before check-in time to activate digital key
    last_audit_completed_at: Optional[datetime] = None
    last_audit_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class TaxCategory(SQLModel, table=True):
    """Tax categories like room_charge, food_beverage, spa, etc.
    Each category maps to a set of charge types."""
    __tablename__ = "taxcategory"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)  # room_charge, food_beverage, liquor, spa, etc.
    display_name: str  # "Room Charges", "Food & Beverages", etc.
    description: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaxSlab(SQLModel, table=True):
    """Tax slabs configurable by category and amount threshold.
    For India: CGST + SGST (intra-state) or IGST (inter-state).
    rate_pct is total rate; component_1_pct + component_2_pct = rate_pct."""
    __tablename__ = "taxslab"

    id: Optional[int] = Field(default=None, primary_key=True)
    tax_category_id: int = Field(foreign_key="taxcategory.id", index=True)
    country: str = Field(default="IN", index=True)  # ISO country code
    min_amount: float = Field(default=0.0)  # Threshold: apply if charge >= min_amount
    max_amount: Optional[float] = None  # None = no upper limit
    rate_pct: float  # Total tax rate, e.g. 18.0 for 18%
    component_1_name: str = Field(default="CGST")
    component_1_pct: float = 0.0  # e.g. 9.0
    component_2_name: str = Field(default="SGST")
    component_2_pct: float = 0.0  # e.g. 9.0
    effective_from: date_type = Field(default_factory=date.today)
    effective_to: Optional[date_type] = None  # None = currently active
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class TransactionCode(SQLModel, table=True):
    """Opera-style numeric transaction codes mapping to charge/payment categories.
    Each code has a matching adjustment code for reversals."""
    __tablename__ = "transactioncode"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)  # "1000", "2000", etc.
    name: str  # "Room Charge", "Minibar", etc.
    category: str = Field(index=True)  # Maps to FolioLineItem.item_type (room_charge, minibar, etc.)
    code_type: str = Field(default="charge", index=True)  # charge, payment, adjustment, tax
    adjustment_code: Optional[str] = None  # Matching adjustment code (e.g., "1001" for "1000")
    department: Optional[str] = None  # Rooms, F&B, Spa, etc.
    is_active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    """General PMS operation audit log — tracks who did what, from where."""
    __tablename__ = "auditlog"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    action: str = Field(index=True)  # check_in, check_out, post_charge, settle_folio, void, adjust, etc.
    entity_type: str = Field(index=True)  # booking, folio, payment, room, guest
    entity_id: Optional[int] = Field(default=None, index=True)
    description: str  # Human-readable description of the action
    old_value: Optional[str] = Field(default=None, sa_column=Column(JSON))  # Previous state (JSON)
    new_value: Optional[str] = Field(default=None, sa_column=Column(JSON))  # New state (JSON)
    workstation_id: Optional[str] = Field(default=None, index=True)  # Terminal/workstation identifier
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CashierSession(SQLModel, table=True):
    """Per-staff cashier session with cash float tracking.
    Must be opened before posting cash payments, closed before night audit."""
    __tablename__ = "cashiersession"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="users.id", index=True)
    workstation_id: Optional[str] = Field(default=None, index=True)
    session_date: date_type = Field(index=True)
    status: str = Field(default="open", index=True)  # open, closed, suspended
    opening_balance: float = Field(default=0.0)  # Opening cash float
    closing_balance: Optional[float] = None  # Actual cash counted at close
    expected_balance: Optional[float] = None  # Calculated: opening + cash_in - cash_out
    cash_received: float = Field(default=0.0)  # Total cash payments received
    cash_paid_out: float = Field(default=0.0)  # Total cash refunds/payouts
    variance: Optional[float] = None  # closing_balance - expected_balance (+ = over, - = short)
    transaction_count: int = Field(default=0)
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    closed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScheduledRoomMove(SQLModel, table=True):
    """Scheduled room moves for checked-in guests. Can be same-day or future-dated.
    Night audit blocks if unresolved moves exist for the current business date."""
    __tablename__ = "scheduledroomove"

    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key="bookings.id", index=True)
    from_room_id: int = Field(foreign_key="rooms.id")
    to_room_id: int = Field(foreign_key="rooms.id")
    scheduled_date: date_type = Field(index=True)
    move_reason: Optional[str] = None  # upgrade, downgrade, complaint, maintenance, consolidation
    status: str = Field(default="scheduled", index=True)  # scheduled, completed, cancelled
    moved_at: Optional[datetime] = None
    moved_by: Optional[int] = Field(default=None, foreign_key="users.id")
    notes: Optional[str] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PaymasterAccount(SQLModel, table=True):
    """Holding account for disputed, unassigned, or group charges.
    Charges can be parked here and later transferred to a specific booking."""
    __tablename__ = "paymasteraccount"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_name: str = Field(default="Paymaster")
    account_code: Optional[str] = Field(default=None, unique=True, index=True)
    status: str = Field(default="active", index=True)  # active, closed
    total_charges: float = Field(default=0.0)
    total_transferred: float = Field(default=0.0)
    current_balance: float = Field(default=0.0)  # total_charges - total_transferred
    notes: Optional[str] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PaymasterPosting(SQLModel, table=True):
    """Individual charge or transfer in/out of a paymaster account."""
    __tablename__ = "paymasterposting"

    id: Optional[int] = Field(default=None, primary_key=True)
    paymaster_account_id: int = Field(foreign_key="paymasteraccount.id", index=True)
    posting_type: str = Field(index=True)  # charge_in, transfer_out, adjustment, write_off
    amount: float
    balance_after: float  # Running balance snapshot
    description: str
    source_booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id")
    source_folio_id: Optional[int] = None
    source_line_item_id: Optional[int] = None
    target_booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id")  # For transfer_out
    target_folio_id: Optional[int] = None  # For transfer_out
    posted_by: Optional[int] = Field(default=None, foreign_key="users.id")
    posted_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None


class PosOutlet(SQLModel, table=True):
    """Point-of-sale outlet (restaurant, bar, spa, minibar, etc.).
    Each outlet must confirm closure before night audit can proceed."""
    __tablename__ = "posoutlet"

    id: Optional[int] = Field(default=None, primary_key=True)
    outlet_code: str = Field(unique=True, index=True)  # restaurant, bar, spa, minibar, laundry
    outlet_name: str
    location: Optional[str] = None
    responsible_staff_id: Optional[int] = Field(default=None, foreign_key="users.id")
    status: str = Field(default="active", index=True)  # active, inactive
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PosClosure(SQLModel, table=True):
    """Daily closure confirmation for a POS outlet.
    Night audit blocks until all active outlets confirm closure."""
    __tablename__ = "posclosure"

    id: Optional[int] = Field(default=None, primary_key=True)
    pos_outlet_id: int = Field(foreign_key="posoutlet.id", index=True)
    audit_date: date_type = Field(index=True)
    close_status: str = Field(default="pending", index=True)  # pending, confirmed
    closing_revenue: Optional[float] = None
    open_checks: int = Field(default=0)  # Outstanding checks at close time
    discrepancy_notes: Optional[str] = None
    confirmed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    confirmed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditSignOff(SQLModel, table=True):
    """Multi-signature approval for night audit evaluation pack.
    Requires sequential approval: duty_manager → general_manager → finance_controller."""
    __tablename__ = "auditsignoff"

    id: Optional[int] = Field(default=None, primary_key=True)
    audit_id: int = Field(foreign_key="nightaudit.id", index=True)
    role: str = Field(index=True)  # duty_manager, general_manager, finance_controller
    sign_order: int  # 1, 2, 3
    status: str = Field(default="pending", index=True)  # pending, approved, rejected
    staff_id: Optional[int] = Field(default=None, foreign_key="users.id")
    signed_at: Optional[datetime] = None
    comments: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

