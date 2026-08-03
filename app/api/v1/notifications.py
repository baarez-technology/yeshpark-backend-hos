"""
Staff Notifications API Endpoints
Handles notifications for staff members
"""
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, and_, or_, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.staff import Staff
from app.models.guest_chat import StaffNotification, StaffTask

router = APIRouter()


# ============== SCHEMAS ==============

class NotificationRead(BaseModel):
    id: int
    staff_id: int
    task_id: Optional[int] = None
    notification_type: str
    title: str
    message: str
    # Entity references for navigation (clicking notification highlights the entity)
    guest_id: Optional[int] = None
    booking_id: Optional[int] = None
    room_id: Optional[int] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime
    task: Optional[dict] = None

    class Config:
        from_attributes = True


class NotificationCreate(BaseModel):
    staff_id: int
    task_id: Optional[int] = None
    notification_type: str = "info"  # task_assigned, task_reminder, task_update, alert, info, system
    title: str
    message: str


class NotificationUpdate(BaseModel):
    is_read: Optional[bool] = None


class NotificationStats(BaseModel):
    total: int
    unread: int
    by_type: dict


# ============== ENDPOINTS ==============

@router.get("", response_model=List[NotificationRead])
async def list_notifications(
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    notification_type: Optional[str] = Query(None, description="Filter by notification type"),
    limit: int = Query(50, le=100, description="Maximum number of notifications"),
    offset: int = Query(0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List notifications for the current user"""
    query = select(StaffNotification).where(
        StaffNotification.staff_id == current_user.id
    )

    if is_read is not None:
        query = query.where(StaffNotification.is_read == is_read)
    if notification_type:
        query = query.where(StaffNotification.notification_type == notification_type)

    query = query.order_by(StaffNotification.created_at.desc())
    query = query.offset(offset).limit(limit)

    result = await session.exec(query)
    notifications = result.all()

    # Enrich with task data
    notification_list = []
    for notif in notifications:
        notif_dict = {
            "id": notif.id,
            "staff_id": notif.staff_id,
            "task_id": notif.task_id,
            "notification_type": notif.notification_type,
            "title": notif.title,
            "message": notif.message,
            "guest_id": notif.guest_id,
            "booking_id": notif.booking_id,
            "room_id": notif.room_id,
            "is_read": notif.is_read,
            "read_at": notif.read_at,
            "created_at": notif.created_at,
            "task": None
        }

        if notif.task_id:
            task_result = await session.exec(
                select(StaffTask).where(StaffTask.id == notif.task_id)
            )
            task = task_result.first()
            if task:
                notif_dict["task"] = {
                    "id": task.id,
                    "task_type": task.task_type,
                    "title": task.title,
                    "status": task.status,
                    "priority": task.priority,
                    "room_number": task.room_number
                }

        notification_list.append(NotificationRead(**notif_dict))

    return notification_list


@router.get("/unread-count")
async def get_unread_count(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get count of unread notifications"""
    result = await session.exec(
        select(func.count(StaffNotification.id)).where(
            and_(
                StaffNotification.staff_id == current_user.id,
                StaffNotification.is_read == False
            )
        )
    )
    count = result.one() or 0
    return {"unread_count": count}


@router.get("/stats", response_model=NotificationStats)
async def get_notification_stats(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get notification statistics for the current user"""
    # Total count
    total_result = await session.exec(
        select(func.count(StaffNotification.id)).where(
            StaffNotification.staff_id == current_user.id
        )
    )
    total = total_result.one() or 0

    # Unread count
    unread_result = await session.exec(
        select(func.count(StaffNotification.id)).where(
            and_(
                StaffNotification.staff_id == current_user.id,
                StaffNotification.is_read == False
            )
        )
    )
    unread = unread_result.one() or 0

    # Count by type
    by_type = {}
    for ntype in ["task_assigned", "task_reminder", "task_update", "alert", "info", "system"]:
        type_result = await session.exec(
            select(func.count(StaffNotification.id)).where(
                and_(
                    StaffNotification.staff_id == current_user.id,
                    StaffNotification.notification_type == ntype
                )
            )
        )
        count = type_result.one() or 0
        if count > 0:
            by_type[ntype] = count

    return NotificationStats(total=total, unread=unread, by_type=by_type)


@router.get("/{notification_id}", response_model=NotificationRead)
async def get_notification(
    notification_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a specific notification"""
    result = await session.exec(
        select(StaffNotification).where(
            and_(
                StaffNotification.id == notification_id,
                StaffNotification.staff_id == current_user.id
            )
        )
    )
    notif = result.first()

    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif_dict = {
        "id": notif.id,
        "staff_id": notif.staff_id,
        "task_id": notif.task_id,
        "notification_type": notif.notification_type,
        "title": notif.title,
        "message": notif.message,
        "guest_id": notif.guest_id,
        "booking_id": notif.booking_id,
        "room_id": notif.room_id,
        "is_read": notif.is_read,
        "read_at": notif.read_at,
        "created_at": notif.created_at,
        "task": None
    }

    if notif.task_id:
        task_result = await session.exec(
            select(StaffTask).where(StaffTask.id == notif.task_id)
        )
        task = task_result.first()
        if task:
            notif_dict["task"] = {
                "id": task.id,
                "task_type": task.task_type,
                "title": task.title,
                "status": task.status,
                "priority": task.priority,
                "room_number": task.room_number
            }

    return NotificationRead(**notif_dict)


@router.post("", response_model=NotificationRead)
async def create_notification(
    payload: NotificationCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new notification (admin/system use)"""
    notification = StaffNotification(
        staff_id=payload.staff_id,
        task_id=payload.task_id,
        notification_type=payload.notification_type,
        title=payload.title,
        message=payload.message,
        is_read=False,
        created_at=datetime.utcnow()
    )

    session.add(notification)
    await session.commit()
    await session.refresh(notification)

    return NotificationRead(**{k: v for k, v in notification.__dict__.items() if not k.startswith('_')})


@router.patch("/{notification_id}", response_model=NotificationRead)
async def update_notification(
    notification_id: int,
    payload: NotificationUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a notification (mark as read/unread)"""
    result = await session.exec(
        select(StaffNotification).where(
            and_(
                StaffNotification.id == notification_id,
                StaffNotification.staff_id == current_user.id
            )
        )
    )
    notif = result.first()

    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    if payload.is_read is not None:
        notif.is_read = payload.is_read
        if payload.is_read:
            notif.read_at = datetime.utcnow()
        else:
            notif.read_at = None

    await session.commit()
    await session.refresh(notif)

    return NotificationRead(**{k: v for k, v in notif.__dict__.items() if not k.startswith('_')})


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark a notification as read"""
    result = await session.exec(
        select(StaffNotification).where(
            and_(
                StaffNotification.id == notification_id,
                StaffNotification.staff_id == current_user.id
            )
        )
    )
    notif = result.first()

    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.is_read = True
    notif.read_at = datetime.utcnow()

    await session.commit()
    await session.refresh(notif)

    return NotificationRead(**{k: v for k, v in notif.__dict__.items() if not k.startswith('_')})


@router.post("/mark-all-read")
async def mark_all_notifications_read(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Mark all notifications as read for the current user"""
    result = await session.exec(
        select(StaffNotification).where(
            and_(
                StaffNotification.staff_id == current_user.id,
                StaffNotification.is_read == False
            )
        )
    )
    notifications = result.all()

    now = datetime.utcnow()
    for notif in notifications:
        notif.is_read = True
        notif.read_at = now

    await session.commit()

    return {"message": f"Marked {len(notifications)} notifications as read"}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a notification"""
    result = await session.exec(
        select(StaffNotification).where(
            and_(
                StaffNotification.id == notification_id,
                StaffNotification.staff_id == current_user.id
            )
        )
    )
    notif = result.first()

    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    await session.delete(notif)
    await session.commit()

    return {"message": "Notification deleted"}


@router.delete("")
async def delete_all_notifications(
    only_read: bool = Query(False, description="Only delete read notifications"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete all notifications for the current user"""
    query = select(StaffNotification).where(
        StaffNotification.staff_id == current_user.id
    )

    if only_read:
        query = query.where(StaffNotification.is_read == True)

    result = await session.exec(query)
    notifications = result.all()

    for notif in notifications:
        await session.delete(notif)

    await session.commit()

    return {"message": f"Deleted {len(notifications)} notifications"}
