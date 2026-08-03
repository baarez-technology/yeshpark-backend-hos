"""
Audit Log API — General PMS operation audit trail with workstation tracking.
"""

import csv
import io
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import AuditLog

router = APIRouter()


def serialize_log(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "user_id": log.user_id,
        "action": log.action,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "description": log.description,
        "old_value": log.old_value,
        "new_value": log.new_value,
        "workstation_id": log.workstation_id,
        "ip_address": log.ip_address,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


async def create_audit_log(
    session: AsyncSession,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    description: str,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    workstation_id: Optional[str] = None,
    ip_address: Optional[str] = None,
):
    """Helper to create an audit log entry. Call from other endpoints."""
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        old_value=old_value,
        new_value=new_value,
        workstation_id=workstation_id,
        ip_address=ip_address,
    )
    session.add(log)
    return log


@router.get("")
async def list_audit_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    user_id: Optional[int] = None,
    workstation_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List audit logs with filters. Admin/GM only."""
    if current_user.role not in ("admin", "general_manager", "finance_controller", "front_office_manager"):
        raise HTTPException(403, "Insufficient permissions to view audit logs")

    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if workstation_id:
        query = query.where(AuditLog.workstation_id == workstation_id)

    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    results = (await session.exec(query)).all()
    return {"items": [serialize_log(log) for log in results]}


@router.get("/{log_id}")
async def get_audit_log(
    log_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    log = await session.get(AuditLog, log_id)
    if not log:
        raise HTTPException(404, "Audit log entry not found")
    return serialize_log(log)


@router.get("/export/csv")
async def export_audit_logs_csv(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(5000, ge=1, le=10000),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Export audit logs as CSV for compliance audits."""
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(403, "Insufficient permissions")

    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if date_from:
        query = query.where(AuditLog.created_at >= date_from)
    if date_to:
        query = query.where(AuditLog.created_at <= date_to + "T23:59:59")

    query = query.order_by(AuditLog.created_at.desc()).limit(limit)
    results = (await session.exec(query)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp", "User ID", "Action", "Entity Type", "Entity ID",
                     "Description", "Workstation", "IP Address", "Old Value", "New Value"])
    for log in results:
        writer.writerow([
            log.id,
            log.created_at.isoformat() if log.created_at else "",
            log.user_id or "",
            log.action,
            log.entity_type,
            log.entity_id or "",
            log.description,
            log.workstation_id or "",
            log.ip_address or "",
            str(log.old_value or ""),
            str(log.new_value or ""),
        ])

    output.seek(0)
    filename = f"audit_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
