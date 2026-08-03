"""
Tenant middleware for multi-tenant hotel management.

Extracts hotel context from JWT tokens or X-Hotel-Code header
and makes it available to all request handlers via request.state.hotel_code.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from jose import jwt, JWTError
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Extract hotel context and set on request.state.

    Priority order for hotel_code:
    1. JWT token "hotel_code" claim (authenticated users)
    2. X-Hotel-Code header (unauthenticated public pages)
    3. hotel_code query parameter (fallback)

    This allows both authenticated and unauthenticated users to access
    tenant-specific data (e.g., browsing rooms, making bookings).
    """

    # Public routes that don't need tenant context at all
    PUBLIC_PATHS = {
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/signup",
        "/api/v1/auth/token",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/verify-reset-token",
        "/api/v1/auth/verify-email",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    # Path prefixes that don't need tenant context
    PUBLIC_PREFIXES = (
        "/docs",
        "/redoc",
        "/static",
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        # Initialize hotel_code to None
        request.state.hotel_code = None

        # Skip if multi-tenant is not enabled
        if not settings.multi_tenant_enabled:
            return await call_next(request)

        # Skip public paths that truly don't need tenant context
        path = request.url.path
        if path in self.PUBLIC_PATHS or path.startswith(self.PUBLIC_PREFIXES):
            return await call_next(request)

        hotel_code = None

        # Priority 1: Extract from JWT token (authenticated users)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                payload = jwt.decode(
                    token,
                    settings.secret_key,
                    algorithms=["HS256"]
                )
                hotel_code = payload.get("hotel_code")
            except JWTError as e:
                # Invalid token - continue to check other sources
                logger.debug(f"JWT decode error in tenant middleware: {e}")

        # Priority 2: X-Hotel-Code header (unauthenticated public pages)
        if not hotel_code:
            hotel_code = request.headers.get("X-Hotel-Code")

        # Priority 3: Query parameter (fallback for some API calls)
        if not hotel_code:
            hotel_code = request.query_params.get("hotel_code")

        # Set hotel context on request state
        request.state.hotel_code = hotel_code

        if hotel_code:
            logger.debug(f"Tenant context set: {hotel_code} for {path}")

        response = await call_next(request)
        return response
