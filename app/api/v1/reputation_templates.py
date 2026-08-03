"""
Reputation AI - Response Template Management
Handles CRUD operations for review response templates
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel, Field

from app.db.session import get_tenant_session
from app.services.reputation_service import ReputationService
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.reputation import ResponseTemplate

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== PYDANTIC SCHEMAS ====================

class CreateTemplateRequest(BaseModel):
    name: str = Field(..., max_length=100)
    content: str = Field(..., description="Template content with {guest_name} placeholder")
    tone: str = Field(default="professional")
    sentiment: str = Field(default="positive", description="Target sentiment: positive, neutral, negative")
    is_default: bool = Field(default=False)


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    tone: Optional[str] = None
    sentiment: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


# ==================== TEMPLATE ROUTES ====================

@router.get("/")
async def get_response_templates(
    tone: Optional[str] = None,
    sentiment: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get all response templates.
    Used for managing fallback content.
    """
    service = ReputationService(db)
    return await service.get_templates(tone=tone, sentiment=sentiment)


@router.post("/")
async def create_response_template(
    request: CreateTemplateRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new response template.
    """
    service = ReputationService(db)
    try:
        return await service.create_template(
            name=request.name,
            content=request.content,
            tone=request.tone,
            sentiment=request.sentiment,
            is_default=request.is_default,
            created_by=current_user.id
        )
    except Exception as e:
        logger.error(f"Error creating template: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create template"
        )


@router.patch("/{template_id}")
async def update_response_template(
    template_id: int,
    request: UpdateTemplateRequest,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Update an existing response template.
    """
    service = ReputationService(db)
    try:
        # Convert dictionary to key-value arguments for update
        update_data = request.dict(exclude_unset=True)
        return await service.update_template(template_id, **update_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating template: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update template"
        )


@router.delete("/{template_id}")
async def delete_response_template(
    template_id: int,
    db: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Delete (deactivate) a response template.
    """
    service = ReputationService(db)
    try:
        await service.delete_template(template_id)
        return {"success": True, "message": "Template deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting template: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete template"
        )
