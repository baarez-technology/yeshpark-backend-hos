"""Middleware modules for Glimmora Hotel Management System."""
from app.middleware.tenant import TenantMiddleware

__all__ = ["TenantMiddleware"]
