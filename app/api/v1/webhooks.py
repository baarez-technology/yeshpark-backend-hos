"""
SSE Event helper for background tasks
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

async def broadcast_sse_event(event_type: str, data: Dict[str, Any]):
    """Helper function to handle background SSE event broadcasts"""
    logger.debug(f"[SSE Broadcast] Event: {event_type}, Data: {data}")
