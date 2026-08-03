#!/usr/bin/env python3
"""
Hotel Provisioning Script for Glimmora Multi-Tenant Architecture.

Creates a new hotel database and registers it in the master database.

Usage:
    python -m app.scripts.provision_hotel "Grand Hyatt Mumbai" "hyatt_mumbai" --city "Mumbai" --country "India"

Arguments:
    name: Hotel name (e.g., "Grand Hyatt Mumbai")
    code: Unique hotel code, lowercase with underscores (e.g., "hyatt_mumbai")

Options:
    --city: City where hotel is located
    --country: Country where hotel is located
    --timezone: Timezone (default: UTC)
    --currency: Currency code (default: INR)
    --tier: Subscription tier: standard, premium, enterprise (default: standard)
"""
import asyncio
import argparse
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def provision_new_hotel(
    name: str,
    code: str,
    city: str = None,
    country: str = None,
    timezone: str = "UTC",
    currency: str = "INR",
    subscription_tier: str = "standard",
) -> bool:
    """
    Create a new hotel database and register in master DB.

    Args:
        name: Human-readable hotel name
        code: Unique hotel code (lowercase, underscores allowed)
        city: City where hotel is located
        country: Country where hotel is located
        timezone: Timezone for the hotel
        currency: Currency code (INR, USD, EUR, etc.)
        subscription_tier: Subscription level (standard, premium, enterprise)

    Returns:
        True if successful, False otherwise
    """
    # Import here to avoid circular imports and ensure settings are loaded
    from app.core.config import settings
    from app.db.tenant_manager import tenant_manager
    from app.db.master_models import Hotel
    from app.db.session import init_hotel_db
    from sqlmodel import select

    # Validate code format
    if not code.replace("_", "").isalnum() or not code.islower():
        logger.error(f"Invalid hotel code: {code}")
        logger.error("Hotel code must be lowercase alphanumeric with underscores only")
        return False

    db_name = f"glimmora_{code}"

    logger.info(f"Provisioning hotel: {name} ({code})")
    logger.info(f"Database name: {db_name}")

    # Step 1: Check if hotel already exists in master DB
    try:
        async with tenant_manager.master_session_maker() as session:
            existing = await session.exec(
                select(Hotel).where(Hotel.code == code)
            )
            if existing.first():
                logger.error(f"Hotel with code '{code}' already exists!")
                return False
    except Exception as e:
        logger.error(f"Failed to check master database: {e}")
        return False

    # Step 2: Create PostgreSQL database
    try:
        import asyncpg

        # Connect to default 'postgres' database to create new database
        conn = await asyncpg.connect(
            user=settings.db_user,
            password=settings.db_password,
            host=settings.db_host,
            port=settings.db_port,
            database="postgres"
        )

        try:
            # Create the database
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            logger.info(f"Created database: {db_name}")
        except asyncpg.DuplicateDatabaseError:
            logger.warning(f"Database {db_name} already exists, continuing...")
        finally:
            await conn.close()

    except ImportError:
        logger.error("asyncpg not installed. Install with: pip install asyncpg")
        return False
    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        return False

    # Step 3: Create tables in new database
    try:
        # Add hotel to cache temporarily so init_hotel_db can find it
        tenant_manager._hotel_db_map[code] = db_name

        await init_hotel_db(code)
        logger.info(f"Created tables in {db_name}")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        # Clean up cache
        tenant_manager._hotel_db_map.pop(code, None)
        return False

    # Step 4: Register in master database
    try:
        async with tenant_manager.master_session_maker() as session:
            hotel = Hotel(
                name=name,
                code=code,
                db_name=db_name,
                city=city,
                country=country,
                timezone=timezone,
                currency=currency,
                subscription_tier=subscription_tier,
                is_active=True,
            )
            session.add(hotel)
            await session.commit()
            logger.info(f"Registered hotel in master database")
    except Exception as e:
        logger.error(f"Failed to register hotel: {e}")
        return False

    # Success!
    logger.info("")
    logger.info("=" * 50)
    logger.info(f"Hotel '{name}' provisioned successfully!")
    logger.info("=" * 50)
    logger.info(f"  Code:     {code}")
    logger.info(f"  Database: {db_name}")
    logger.info(f"  City:     {city or 'N/A'}")
    logger.info(f"  Country:  {country or 'N/A'}")
    logger.info(f"  Timezone: {timezone}")
    logger.info(f"  Currency: {currency}")
    logger.info(f"  Tier:     {subscription_tier}")
    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. Create admin user for the hotel")
    logger.info("  2. Configure hotel settings")
    logger.info("  3. Add room types and rooms")
    logger.info("")

    return True


async def list_hotels():
    """List all registered hotels."""
    from app.db.tenant_manager import tenant_manager
    from app.db.master_models import Hotel
    from sqlmodel import select

    try:
        async with tenant_manager.master_session_maker() as session:
            result = await session.exec(select(Hotel).order_by(Hotel.created_at.desc()))
            hotels = result.all()

            if not hotels:
                print("No hotels registered yet.")
                return

            print("\nRegistered Hotels:")
            print("-" * 80)
            print(f"{'Code':<25} {'Name':<30} {'Status':<10} {'Tier':<12}")
            print("-" * 80)

            for hotel in hotels:
                status = "Active" if hotel.is_active else "Inactive"
                print(f"{hotel.code:<25} {hotel.name[:28]:<30} {status:<10} {hotel.subscription_tier:<12}")

            print("-" * 80)
            print(f"Total: {len(hotels)} hotel(s)")

    except Exception as e:
        logger.error(f"Failed to list hotels: {e}")


async def deactivate_hotel(code: str):
    """Deactivate a hotel (soft delete)."""
    from app.db.tenant_manager import tenant_manager
    from app.db.master_models import Hotel
    from sqlmodel import select
    from datetime import datetime

    try:
        async with tenant_manager.master_session_maker() as session:
            result = await session.exec(select(Hotel).where(Hotel.code == code))
            hotel = result.first()

            if not hotel:
                logger.error(f"Hotel not found: {code}")
                return False

            hotel.is_active = False
            hotel.updated_at = datetime.utcnow()
            await session.commit()

            # Invalidate cache
            tenant_manager.invalidate_hotel_cache(code)

            logger.info(f"Hotel '{hotel.name}' ({code}) has been deactivated")
            return True

    except Exception as e:
        logger.error(f"Failed to deactivate hotel: {e}")
        return False


async def activate_hotel(code: str):
    """Reactivate a deactivated hotel."""
    from app.db.tenant_manager import tenant_manager
    from app.db.master_models import Hotel
    from sqlmodel import select
    from datetime import datetime

    try:
        async with tenant_manager.master_session_maker() as session:
            result = await session.exec(select(Hotel).where(Hotel.code == code))
            hotel = result.first()

            if not hotel:
                logger.error(f"Hotel not found: {code}")
                return False

            hotel.is_active = True
            hotel.updated_at = datetime.utcnow()
            await session.commit()

            logger.info(f"Hotel '{hotel.name}' ({code}) has been activated")
            return True

    except Exception as e:
        logger.error(f"Failed to activate hotel: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Glimmora Hotel Provisioning Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a new hotel
  python -m app.scripts.provision_hotel create "Grand Hyatt Mumbai" "hyatt_mumbai" --city Mumbai --country India

  # List all hotels
  python -m app.scripts.provision_hotel list

  # Deactivate a hotel
  python -m app.scripts.provision_hotel deactivate hyatt_mumbai

  # Reactivate a hotel
  python -m app.scripts.provision_hotel activate hyatt_mumbai
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Create command
    create_parser = subparsers.add_parser("create", help="Create a new hotel")
    create_parser.add_argument("name", help="Hotel name (e.g., 'Grand Hyatt Mumbai')")
    create_parser.add_argument("code", help="Unique hotel code (e.g., 'hyatt_mumbai')")
    create_parser.add_argument("--city", help="City where hotel is located")
    create_parser.add_argument("--country", help="Country where hotel is located")
    create_parser.add_argument("--timezone", default="UTC", help="Timezone (default: UTC)")
    create_parser.add_argument("--currency", default="INR", help="Currency code (default: INR)")
    create_parser.add_argument(
        "--tier",
        default="standard",
        choices=["standard", "premium", "enterprise"],
        help="Subscription tier (default: standard)"
    )

    # List command
    subparsers.add_parser("list", help="List all registered hotels")

    # Deactivate command
    deactivate_parser = subparsers.add_parser("deactivate", help="Deactivate a hotel")
    deactivate_parser.add_argument("code", help="Hotel code to deactivate")

    # Activate command
    activate_parser = subparsers.add_parser("activate", help="Activate a hotel")
    activate_parser.add_argument("code", help="Hotel code to activate")

    args = parser.parse_args()

    if args.command == "create":
        success = asyncio.run(provision_new_hotel(
            name=args.name,
            code=args.code,
            city=args.city,
            country=args.country,
            timezone=args.timezone,
            currency=args.currency,
            subscription_tier=args.tier,
        ))
        sys.exit(0 if success else 1)

    elif args.command == "list":
        asyncio.run(list_hotels())

    elif args.command == "deactivate":
        success = asyncio.run(deactivate_hotel(args.code))
        sys.exit(0 if success else 1)

    elif args.command == "activate":
        success = asyncio.run(activate_hotel(args.code))
        sys.exit(0 if success else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
