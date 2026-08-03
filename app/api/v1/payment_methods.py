from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.payment_method import PaymentMethod
from app.models.user import User

router = APIRouter()


class PaymentMethodCreate(BaseModel):
    card_type: str  # visa, mastercard, amex
    last4: str
    expiry_month: int
    expiry_year: int
    cardholder_name: Optional[str] = None
    is_default: bool = False
    card_token: Optional[str] = None  # For payment processor integration


class PaymentMethodUpdate(BaseModel):
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    cardholder_name: Optional[str] = None


class PaymentMethodRead(BaseModel):
    id: int
    user_id: int
    card_type: str
    last4: str
    expiry_month: int
    expiry_year: int
    cardholder_name: Optional[str] = None
    is_default: bool
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[PaymentMethodRead])
async def list_payment_methods(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all payment methods for current user"""
    result = await session.exec(
        select(PaymentMethod).where(
            and_(
                PaymentMethod.user_id == current_user.id,
                PaymentMethod.deleted_at.is_(None)
            )
        ).order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
    )
    methods = result.all()
    return [
        PaymentMethodRead(
            id=m.id,
            user_id=m.user_id,
            card_type=m.card_type,
            last4=m.last4,
            expiry_month=m.expiry_month,
            expiry_year=m.expiry_year,
            cardholder_name=m.cardholder_name,
            is_default=m.is_default,
            is_active=m.is_active,
            created_at=m.created_at.isoformat() if m.created_at else "",
            updated_at=m.updated_at.isoformat() if m.updated_at else "",
        )
        for m in methods
    ]


@router.post("", response_model=PaymentMethodRead, status_code=status.HTTP_201_CREATED)
async def create_payment_method(
    payload: PaymentMethodCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new payment method"""
    # If setting as default, unset other defaults
    if payload.is_default:
        existing_defaults = await session.exec(
            select(PaymentMethod).where(
                and_(
                    PaymentMethod.user_id == current_user.id,
                    PaymentMethod.is_default == True,
                    PaymentMethod.deleted_at.is_(None)
                )
            )
        )
        for method in existing_defaults.all():
            method.is_default = False
            session.add(method)
    
    # Create new payment method
    payment_method = PaymentMethod(
        user_id=current_user.id,
        card_type=payload.card_type,
        last4=payload.last4,
        expiry_month=payload.expiry_month,
        expiry_year=payload.expiry_year,
        cardholder_name=payload.cardholder_name,
        is_default=payload.is_default,
        card_token=payload.card_token,
    )
    
    session.add(payment_method)
    await session.commit()
    await session.refresh(payment_method)
    
    return PaymentMethodRead(
        id=payment_method.id,
        user_id=payment_method.user_id,
        card_type=payment_method.card_type,
        last4=payment_method.last4,
        expiry_month=payment_method.expiry_month,
        expiry_year=payment_method.expiry_year,
        cardholder_name=payment_method.cardholder_name,
        is_default=payment_method.is_default,
        is_active=payment_method.is_active,
        created_at=payment_method.created_at.isoformat() if payment_method.created_at else "",
        updated_at=payment_method.updated_at.isoformat() if payment_method.updated_at else "",
    )


@router.patch("/{payment_method_id}", response_model=PaymentMethodRead)
async def update_payment_method(
    payment_method_id: int,
    payload: PaymentMethodUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a payment method"""
    payment_method = await session.get(PaymentMethod, payment_method_id)
    if not payment_method:
        raise HTTPException(status_code=404, detail="Payment method not found")
    
    if payment_method.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if payment_method.deleted_at:
        raise HTTPException(status_code=404, detail="Payment method not found")
    
    # If setting as default, unset other defaults
    if payload.is_default is True:
        existing_defaults = await session.exec(
            select(PaymentMethod).where(
                and_(
                    PaymentMethod.user_id == current_user.id,
                    PaymentMethod.id != payment_method_id,
                    PaymentMethod.is_default == True,
                    PaymentMethod.deleted_at.is_(None)
                )
            )
        )
        for method in existing_defaults.all():
            method.is_default = False
            session.add(method)
    
    # Update fields
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(payment_method, key, value)
    
    await session.commit()
    await session.refresh(payment_method)
    
    return PaymentMethodRead(
        id=payment_method.id,
        user_id=payment_method.user_id,
        card_type=payment_method.card_type,
        last4=payment_method.last4,
        expiry_month=payment_method.expiry_month,
        expiry_year=payment_method.expiry_year,
        cardholder_name=payment_method.cardholder_name,
        is_default=payment_method.is_default,
        is_active=payment_method.is_active,
        created_at=payment_method.created_at.isoformat() if payment_method.created_at else "",
        updated_at=payment_method.updated_at.isoformat() if payment_method.updated_at else "",
    )


@router.delete("/{payment_method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment_method(
    payment_method_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete (soft delete) a payment method"""
    payment_method = await session.get(PaymentMethod, payment_method_id)
    if not payment_method:
        raise HTTPException(status_code=404, detail="Payment method not found")
    
    if payment_method.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if payment_method.deleted_at:
        raise HTTPException(status_code=404, detail="Payment method not found")
    
    if payment_method.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete default payment method")
    
    # Soft delete
    from datetime import datetime
    payment_method.deleted_at = datetime.utcnow()
    payment_method.is_active = False
    
    await session.commit()

