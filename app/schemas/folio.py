"""Folio/Billing schemas for request/response validation"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# --- Request Models ---

class PostChargeRequest(BaseModel):
    item_type: str = "service"  # room_charge, service, minibar, spa, parking, restaurant, phone, laundry, late_checkout, damage, misc
    description: str
    quantity: float = 1.0
    unit_price: float
    notes: Optional[str] = None


class PostPaymentRequest(BaseModel):
    amount: float
    method: str = "card"  # card, cash, bank_transfer, upi, neft, net_banking, voucher, comp, btc
    payment_type: str = "full_payment"  # deposit, full_payment, partial
    transaction_id: Optional[str] = None
    authorization_code: Optional[str] = None
    card_last4: Optional[str] = None
    card_brand: Optional[str] = None
    upi_id: Optional[str] = None  # UPI VPA (e.g., name@upi)
    notes: Optional[str] = None


class PostRefundRequest(BaseModel):
    amount: float
    reason: str
    original_payment_id: Optional[int] = None
    method: Optional[str] = None  # Defaults to original payment method


class AdjustChargeRequest(BaseModel):
    new_amount: float
    reason: str


class SplitChargeRequest(BaseModel):
    splits: List[dict]  # [{"folio_id": 1, "amount": 50.00}, {"folio_id": 2, "amount": 75.00}]


class TransferChargeRequest(BaseModel):
    line_item_ids: List[int]
    target_folio_id: int
    notes: Optional[str] = None


class CreateFolioRequest(BaseModel):
    folio_type: str = "guest"  # guest, incidental, company
    window_label: Optional[str] = None  # Auto-assigns next letter if not provided


class SettleFolioRequest(BaseModel):
    payment_method: Optional[str] = None  # If balance remains, pay with this (card, cash, btc, etc.)
    corporate_account_id: Optional[int] = None  # Required when payment_method="btc"
    notes: Optional[str] = None


class CrossBookingTransferRequest(BaseModel):
    line_item_ids: List[int]
    target_booking_id: int
    target_folio_id: Optional[int] = None  # If None, uses the first open guest folio
    notes: Optional[str] = None


class MoveToPaymasterRequest(BaseModel):
    line_item_ids: List[int]
    paymaster_account_id: int
    notes: Optional[str] = None


class TransferFromPaymasterRequest(BaseModel):
    posting_ids: List[int]
    target_booking_id: int
    target_folio_id: Optional[int] = None
    notes: Optional[str] = None


class RoutingRuleRequest(BaseModel):
    charge_category: str
    target_folio_id: int
    payment_method: Optional[str] = None
