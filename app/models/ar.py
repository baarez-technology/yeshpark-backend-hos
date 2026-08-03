"""
Accounts Receivable (AR) models for corporate billing.
"""

from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field


class ARAccount(SQLModel, table=True):
    """AR account linked to a corporate account for tracking receivables."""
    __tablename__ = "araccount"

    id: Optional[int] = Field(default=None, primary_key=True)
    corporate_account_id: int = Field(foreign_key="corporate_accounts.id", index=True)
    account_name: str = Field(index=True)
    account_number: str = Field(unique=True, index=True)
    credit_limit: float = Field(default=0.0)
    current_balance: float = Field(default=0.0)
    payment_terms_days: int = Field(default=30)
    status: str = Field(default="active", index=True)  # active, suspended, closed
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ARPosting(SQLModel, table=True):
    """Individual posting (charge, payment, credit note) against an AR account."""
    __tablename__ = "arposting"

    id: Optional[int] = Field(default=None, primary_key=True)
    ar_account_id: int = Field(foreign_key="araccount.id", index=True)
    booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id", index=True)
    folio_id: Optional[int] = Field(default=None, foreign_key="folio.id")
    posting_type: str = Field(index=True)  # charge, payment, credit_note, adjustment
    amount: float
    balance_after: float  # running balance snapshot
    description: str
    reference_number: Optional[str] = Field(default=None, index=True)
    posted_by: Optional[int] = Field(default=None, foreign_key="users.id")
    posted_at: datetime = Field(default_factory=datetime.utcnow)
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None
    status: str = Field(default="pending", index=True)  # pending, paid, overdue, written_off
