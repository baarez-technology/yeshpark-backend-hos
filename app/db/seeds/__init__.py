"""
Glimmora Database Seed Scripts
Provides seed data for all modules based on frontend mock data.
"""

from app.db.seeds.seed_crm_extended import (
    seed_crm_extended_data,
    clear_crm_extended_data
)
from app.db.seeds.seed_rms import seed_rms_data
from app.db.seeds.seed_channel_manager import seed_channel_manager_data
from app.db.seeds.seed_promotions import seed_promotions_data
from app.db.seeds.seed_rbac import seed_rbac_data

__all__ = [
    # CRM Extended
    "seed_crm_extended_data",
    "clear_crm_extended_data",
    # RMS (Revenue Management System)
    "seed_rms_data",
    # Channel Manager
    "seed_channel_manager_data",
    # Promotions & Discounts
    "seed_promotions_data",
    # RBAC (Role-Based Access Control)
    "seed_rbac_data",
]
