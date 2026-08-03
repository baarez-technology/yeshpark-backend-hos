"""
Master Seed Runner Script
Runs all seed scripts in the correct order for Glimmora PMS database.

Usage:
    python -m app.db.seeds.seed_all

Or from the seed runner endpoint (if available):
    POST /api/v1/admin/seed-database
"""
import asyncio
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session_context


async def seed_all_data(
    session: Optional[AsyncSession] = None,
    property_id: int = 1
) -> dict:
    """
    Run all seed scripts in the correct order.

    Args:
        session: Optional existing database session
        property_id: Property ID for multi-tenant data

    Returns:
        Dictionary with stats from each seed script
    """
    stats = {}
    own_session = session is None

    if own_session:
        async with get_async_session_context() as session:
            stats = await _run_all_seeds(session, property_id)
    else:
        stats = await _run_all_seeds(session, property_id)

    return stats


async def _run_all_seeds(session: AsyncSession, property_id: int) -> dict:
    """Internal function to run all seeds with the provided session."""
    stats = {
        "crm_extended": {},
        "rms": {},
        "channel_manager": {},
        "promotions": {},
        "rbac": {},
    }

    print("=" * 60)
    print("GLIMMORA DATABASE SEED RUNNER")
    print("=" * 60)
    print(f"Property ID: {property_id}")
    print("-" * 60)

    # 1. RBAC (no dependencies)
    print("\n[1/5] Seeding RBAC (Roles, Permissions)...")
    try:
        from app.db.seeds.seed_rbac import seed_rbac_data
        stats["rbac"] = await seed_rbac_data(session)
        print("      RBAC seeding complete!")
    except ImportError:
        print("      WARNING: seed_rbac.py not found, skipping...")
        stats["rbac"] = {"skipped": True}
    except Exception as e:
        print(f"      ERROR: {str(e)}")
        stats["rbac"] = {"error": str(e)}

    # 2. CRM Extended (depends on guests existing)
    print("\n[2/5] Seeding CRM Extended (Activity Logs, LTV, Sentiment)...")
    try:
        from app.db.seeds.seed_crm_extended import seed_crm_extended_data
        stats["crm_extended"] = await seed_crm_extended_data(session, property_id)
        print("      CRM Extended seeding complete!")
    except ImportError:
        print("      WARNING: seed_crm_extended.py not found, skipping...")
        stats["crm_extended"] = {"skipped": True}
    except Exception as e:
        print(f"      ERROR: {str(e)}")
        stats["crm_extended"] = {"error": str(e)}

    # 3. RMS (Revenue Management System)
    print("\n[3/5] Seeding RMS (Pricing Rules, Competitors, Forecasts)...")
    try:
        from app.db.seeds.seed_rms import seed_rms_data
        stats["rms"] = await seed_rms_data(session, property_id)
        print("      RMS seeding complete!")
    except ImportError:
        print("      WARNING: seed_rms.py not found, skipping...")
        stats["rms"] = {"skipped": True}
    except Exception as e:
        print(f"      ERROR: {str(e)}")
        stats["rms"] = {"error": str(e)}

    # 4. Channel Manager
    print("\n[4/5] Seeding Channel Manager (OTAs, Mappings, Restrictions)...")
    try:
        from app.db.seeds.seed_channel_manager import seed_channel_manager_data
        stats["channel_manager"] = await seed_channel_manager_data(session, property_id)
        print("      Channel Manager seeding complete!")
    except ImportError:
        print("      WARNING: seed_channel_manager.py not found, skipping...")
        stats["channel_manager"] = {"skipped": True}
    except Exception as e:
        print(f"      ERROR: {str(e)}")
        stats["channel_manager"] = {"error": str(e)}

    # 5. Promotions
    print("\n[5/5] Seeding Promotions (Campaigns, Blackout Dates, Analytics)...")
    try:
        from app.db.seeds.seed_promotions import seed_promotions_data
        stats["promotions"] = await seed_promotions_data(session, property_id)
        print("      Promotions seeding complete!")
    except ImportError:
        print("      WARNING: seed_promotions.py not found, skipping...")
        stats["promotions"] = {"skipped": True}
    except Exception as e:
        print(f"      ERROR: {str(e)}")
        stats["promotions"] = {"error": str(e)}

    print("\n" + "=" * 60)
    print("SEED RUNNER COMPLETE")
    print("=" * 60)

    # Print summary
    print("\nSUMMARY:")
    for module, module_stats in stats.items():
        if isinstance(module_stats, dict):
            if module_stats.get("skipped"):
                print(f"  {module}: SKIPPED")
            elif module_stats.get("error"):
                print(f"  {module}: ERROR - {module_stats['error']}")
            else:
                record_count = sum(v for v in module_stats.values() if isinstance(v, int))
                print(f"  {module}: {record_count} records created")

    return stats


async def clear_all_seed_data(
    session: Optional[AsyncSession] = None,
    property_id: int = 1
) -> dict:
    """
    Clear all seeded data (for testing/development).
    USE WITH CAUTION - this deletes data!

    Args:
        session: Optional existing database session
        property_id: Property ID for multi-tenant data

    Returns:
        Dictionary with clear stats
    """
    stats = {}

    print("=" * 60)
    print("CLEARING ALL SEED DATA")
    print("=" * 60)
    print(f"Property ID: {property_id}")
    print("WARNING: This will delete seeded data!")
    print("-" * 60)

    own_session = session is None

    if own_session:
        async with get_async_session_context() as session:
            stats = await _clear_all_seeds(session, property_id)
    else:
        stats = await _clear_all_seeds(session, property_id)

    return stats


async def _clear_all_seeds(session: AsyncSession, property_id: int) -> dict:
    """Internal function to clear all seeded data."""
    stats = {}

    # Clear in reverse order of dependencies
    modules = [
        ("promotions", "seed_promotions", "clear_promotions_data"),
        ("channel_manager", "seed_channel_manager", "clear_channel_manager_data"),
        ("rms", "seed_rms", "clear_rms_data"),
        ("crm_extended", "seed_crm_extended", "clear_crm_extended_data"),
        ("rbac", "seed_rbac", "clear_rbac_data"),
    ]

    for module_name, module_file, clear_func in modules:
        print(f"\nClearing {module_name}...")
        try:
            module = __import__(f"app.db.seeds.{module_file}", fromlist=[clear_func])
            if hasattr(module, clear_func):
                await getattr(module, clear_func)(session, property_id)
                stats[module_name] = {"cleared": True}
                print(f"  {module_name}: Cleared")
            else:
                stats[module_name] = {"skipped": True, "reason": "No clear function"}
                print(f"  {module_name}: Skipped (no clear function)")
        except ImportError:
            stats[module_name] = {"skipped": True, "reason": "Module not found"}
            print(f"  {module_name}: Skipped (module not found)")
        except Exception as e:
            stats[module_name] = {"error": str(e)}
            print(f"  {module_name}: ERROR - {str(e)}")

    print("\n" + "=" * 60)
    print("CLEAR COMPLETE")
    print("=" * 60)

    return stats


# CLI entry point
if __name__ == "__main__":
    import sys

    async def main():
        if len(sys.argv) > 1 and sys.argv[1] == "--clear":
            property_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            await clear_all_seed_data(property_id=property_id)
        else:
            property_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
            await seed_all_data(property_id=property_id)

    asyncio.run(main())
