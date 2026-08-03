"""
Migration script to create payment_method table
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine, init_db
from app.models.payment_method import PaymentMethod


async def migrate_payment_methods():
    print("Migrating database: Adding payment_method table")
    async with engine.begin() as conn:
        # Create tables if they don't exist
        await conn.run_sync(PaymentMethod.metadata.create_all)
        print("✓ PaymentMethod table created/verified successfully!")


if __name__ == "__main__":
    asyncio.run(migrate_payment_methods())

