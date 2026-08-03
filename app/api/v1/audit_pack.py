"""
Audit Evaluation Pack (B-18).
Multi-signature approval workflow for night audit compliance.
Pre/post audit reports + PDF-ready data export.
"""
import csv
import io
from datetime import datetime, date as date_type
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import NightAudit, AuditSignOff, CashierSession, PosOutlet, PosClosure
from app.models.operations import Folio, FolioLineItem, Payment
from app.models.reservations import Booking
from app.models.inventory import Room

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class SignOffRequest(BaseModel):
    comments: Optional[str] = None


# ── Sign-off Management ─────────────────────────────────────────

@router.post("/{audit_id}/create-signoffs")
async def create_signoff_records(
    audit_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Create the 3-step approval chain for a completed audit.
    Called automatically after night audit completes, or manually."""
    audit = await session.get(NightAudit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Night audit not found")
    if audit.status != "completed":
        raise HTTPException(status_code=400, detail="Can only create sign-offs for completed audits")

    existing = (await session.exec(
        select(AuditSignOff).where(AuditSignOff.audit_id == audit_id)
    )).all()
    if existing:
        raise HTTPException(status_code=409, detail="Sign-off records already exist for this audit")

    roles = [
        ("duty_manager", 1),
        ("general_manager", 2),
        ("finance_controller", 3),
    ]
    for role, order in roles:
        session.add(AuditSignOff(
            audit_id=audit_id,
            role=role,
            sign_order=order,
        ))
    await session.commit()
    return {"message": f"Created 3-step approval chain for audit #{audit_id}"}


@router.get("/{audit_id}/approvals")
async def get_approval_status(
    audit_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Get the multi-signature approval status for an audit."""
    audit = await session.get(NightAudit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Night audit not found")

    signoffs = (await session.exec(
        select(AuditSignOff).where(AuditSignOff.audit_id == audit_id).order_by(AuditSignOff.sign_order)
    )).all()

    if not signoffs:
        return {
            "audit_id": audit_id,
            "audit_date": str(audit.audit_date),
            "approval_status": "no_signoffs_created",
            "approvals": [],
            "fully_approved": False,
        }

    approvals = []
    for s in signoffs:
        staff_name = None
        if s.staff_id:
            user = await session.get(User, s.staff_id)
            staff_name = user.full_name if user else f"User #{s.staff_id}"
        approvals.append({
            "id": s.id,
            "role": s.role,
            "sign_order": s.sign_order,
            "status": s.status,
            "staff_id": s.staff_id,
            "staff_name": staff_name,
            "signed_at": str(s.signed_at) if s.signed_at else None,
            "comments": s.comments,
        })

    fully_approved = all(s.status == "approved" for s in signoffs)
    next_pending = next((s for s in signoffs if s.status == "pending"), None)

    return {
        "audit_id": audit_id,
        "audit_date": str(audit.audit_date),
        "approval_status": "fully_approved" if fully_approved else "pending",
        "approvals": approvals,
        "fully_approved": fully_approved,
        "next_pending_role": next_pending.role if next_pending else None,
    }


@router.post("/{audit_id}/sign-off/{role}")
async def sign_off_audit(
    audit_id: int,
    role: str,
    payload: SignOffRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Sign off on a night audit for a given role. Sequential: previous roles must approve first."""
    valid_roles = {"duty_manager", "general_manager", "finance_controller"}
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

    # Role check: user must have the matching role (or admin)
    role_map = {
        "duty_manager": ["duty_manager", "front_office_manager", "admin"],
        "general_manager": ["general_manager", "admin"],
        "finance_controller": ["finance_controller", "admin"],
    }
    if current_user.role not in role_map.get(role, []):
        raise HTTPException(status_code=403, detail=f"Your role '{current_user.role}' cannot sign off as '{role}'")

    signoff = (await session.exec(
        select(AuditSignOff).where(
            AuditSignOff.audit_id == audit_id,
            AuditSignOff.role == role,
        )
    )).first()
    if not signoff:
        raise HTTPException(status_code=404, detail=f"No sign-off record found for role '{role}' on audit #{audit_id}")
    if signoff.status == "approved":
        raise HTTPException(status_code=409, detail=f"Already approved by {role}")

    # Check sequential: all lower-order sign-offs must be approved
    prior = (await session.exec(
        select(AuditSignOff).where(
            AuditSignOff.audit_id == audit_id,
            AuditSignOff.sign_order < signoff.sign_order,
        )
    )).all()
    unapproved = [p for p in prior if p.status != "approved"]
    if unapproved:
        pending_roles = [p.role for p in unapproved]
        raise HTTPException(
            status_code=400,
            detail=f"Cannot sign off: awaiting approval from {', '.join(pending_roles)}"
        )

    signoff.status = "approved"
    signoff.staff_id = current_user.id
    signoff.signed_at = datetime.utcnow()
    signoff.comments = payload.comments
    session.add(signoff)
    await session.commit()
    await session.refresh(signoff)

    return {"message": f"Audit #{audit_id} signed off by {role}", "signoff": {
        "role": signoff.role,
        "status": signoff.status,
        "signed_at": str(signoff.signed_at),
    }}


@router.post("/{audit_id}/reject/{role}")
async def reject_audit(
    audit_id: int,
    role: str,
    payload: SignOffRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Reject a night audit sign-off (returns for correction)."""
    signoff = (await session.exec(
        select(AuditSignOff).where(
            AuditSignOff.audit_id == audit_id,
            AuditSignOff.role == role,
        )
    )).first()
    if not signoff:
        raise HTTPException(status_code=404, detail="Sign-off not found")

    signoff.status = "rejected"
    signoff.staff_id = current_user.id
    signoff.signed_at = datetime.utcnow()
    signoff.comments = payload.comments or "Rejected — corrections needed"
    session.add(signoff)
    await session.commit()
    return {"message": f"Audit #{audit_id} rejected by {role}"}


# ── Pre/Post Audit Reports ──────────────────────────────────────

@router.get("/{audit_id}/pre-report")
async def get_pre_audit_report(
    audit_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Pre-audit snapshot: state of the hotel before night audit ran."""
    audit = await session.get(NightAudit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Night audit not found")

    target_date = audit.audit_date

    # Room inventory
    all_rooms = (await session.exec(select(Room))).all()
    total_rooms = len([r for r in all_rooms if r.status != "out_of_order"])
    ooo_rooms = len([r for r in all_rooms if r.status == "out_of_order"])

    # POS closure status
    active_outlets = (await session.exec(
        select(PosOutlet).where(PosOutlet.status == "active")
    )).all()
    pos_closures = []
    for outlet in active_outlets:
        closure = (await session.exec(
            select(PosClosure).where(
                PosClosure.pos_outlet_id == outlet.id,
                PosClosure.audit_date == target_date,
            )
        )).first()
        pos_closures.append({
            "outlet": outlet.outlet_name,
            "status": closure.close_status if closure else "pending",
            "revenue": closure.closing_revenue if closure else None,
        })

    # Cashier sessions
    cashier_sessions = (await session.exec(
        select(CashierSession).where(CashierSession.session_date == target_date)
    )).all()

    return {
        "audit_id": audit_id,
        "audit_date": str(target_date),
        "report_type": "pre_audit",
        "generated_at": datetime.utcnow().isoformat(),
        "room_inventory": {
            "total_sellable": total_rooms,
            "out_of_order": ooo_rooms,
        },
        "occupancy_snapshot": {
            "in_house": audit.in_house,
            "arrivals_expected": audit.arrivals,
            "departures_expected": audit.departures,
            "occupancy_rate": audit.occupancy_rate,
        },
        "pos_closures": pos_closures,
        "cashier_sessions": [{
            "staff_id": cs.staff_id,
            "status": cs.status,
            "opening_balance": cs.opening_balance,
            "cash_received": cs.cash_received,
        } for cs in cashier_sessions],
    }


@router.get("/{audit_id}/post-report")
async def get_post_audit_report(
    audit_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Post-audit report: results of the night audit run."""
    audit = await session.get(NightAudit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Night audit not found")

    # Revenue breakdown by charge type
    target_date = audit.audit_date
    line_items = (await session.exec(
        select(FolioLineItem).where(
            FolioLineItem.is_voided == False,
            FolioLineItem.description.contains(str(target_date)),
        )
    )).all()

    revenue_by_type = {}
    total_tax = 0.0
    for li in line_items:
        cat = li.item_type or "other"
        revenue_by_type[cat] = revenue_by_type.get(cat, 0) + (li.amount or 0)
        total_tax += (li.tax_amount or 0)

    # Payment summary for the day
    payments = (await session.exec(
        select(Payment).where(
            Payment.status == "completed"
        )
    )).all()
    # Filter to payments made on audit date (using created_at)
    day_payments = [p for p in payments if p.created_at and p.created_at.date() == target_date]
    payment_by_method = {}
    for p in day_payments:
        method = p.method or "unknown"
        payment_by_method[method] = payment_by_method.get(method, 0) + (p.amount or 0)

    # Sign-off status
    signoffs = (await session.exec(
        select(AuditSignOff).where(AuditSignOff.audit_id == audit_id).order_by(AuditSignOff.sign_order)
    )).all()

    return {
        "audit_id": audit_id,
        "audit_date": str(target_date),
        "report_type": "post_audit",
        "generated_at": datetime.utcnow().isoformat(),
        "audit_summary": {
            "status": audit.status,
            "run_at": str(audit.run_at),
            "completed_at": str(audit.completed_at) if audit.completed_at else None,
            "occupancy_rate": audit.occupancy_rate,
            "in_house": audit.in_house,
            "no_shows": audit.no_shows,
            "auto_checkouts": audit.auto_checkouts,
            "room_charges_posted": audit.room_charges_posted,
            "room_charge_revenue": audit.room_charge_revenue,
        },
        "revenue_breakdown": revenue_by_type,
        "total_tax_collected": round(total_tax, 2),
        "payments_by_method": payment_by_method,
        "total_payments": round(sum(payment_by_method.values()), 2),
        "sign_off_status": [{
            "role": s.role,
            "status": s.status,
            "signed_at": str(s.signed_at) if s.signed_at else None,
        } for s in signoffs],
        "fully_approved": all(s.status == "approved" for s in signoffs) if signoffs else False,
        "errors": audit.errors,
        "notes": audit.notes,
    }


@router.get("/{audit_id}/export-pdf")
async def export_audit_pdf_data(
    audit_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Export night audit evaluation pack as CSV (PDF-ready data).
    Contains pre-report, post-report, and sign-off chain in one file."""
    audit = await session.get(NightAudit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Night audit not found")

    signoffs = (await session.exec(
        select(AuditSignOff).where(AuditSignOff.audit_id == audit_id).order_by(AuditSignOff.sign_order)
    )).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(["NIGHT AUDIT EVALUATION PACK"])
    writer.writerow(["Audit Date", str(audit.audit_date)])
    writer.writerow(["Run At", str(audit.run_at)])
    writer.writerow(["Status", audit.status])
    writer.writerow([])

    # Metrics
    writer.writerow(["AUDIT METRICS"])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Occupancy Rate", f"{audit.occupancy_rate}%"])
    writer.writerow(["Revenue", f"{audit.revenue}"])
    writer.writerow(["In-House Guests", audit.in_house])
    writer.writerow(["Arrivals", audit.arrivals])
    writer.writerow(["Departures", audit.departures])
    writer.writerow(["No-Shows", audit.no_shows])
    writer.writerow(["Auto-Checkouts", audit.auto_checkouts])
    writer.writerow(["Room Charges Posted", audit.room_charges_posted])
    writer.writerow(["Room Charge Revenue", f"{audit.room_charge_revenue}"])
    writer.writerow([])

    # Sign-offs
    writer.writerow(["APPROVAL CHAIN"])
    writer.writerow(["Order", "Role", "Status", "Staff ID", "Signed At", "Comments"])
    for s in signoffs:
        writer.writerow([s.sign_order, s.role, s.status, s.staff_id or "", str(s.signed_at) if s.signed_at else "", s.comments or ""])
    writer.writerow([])

    if audit.errors:
        writer.writerow(["ERRORS"])
        writer.writerow([audit.errors])

    output.seek(0)
    filename = f"audit_pack_{audit.audit_date}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
