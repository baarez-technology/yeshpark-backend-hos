"""
Script to create password reset token table
"""
import asyncio
from app.db.session import engine, init_db
from app.models.password_reset import PasswordResetToken

async def migrate_password_reset():
    """Create password reset token table"""
    print("=" * 60, flush=True)
    print("CREATING PASSWORD RESET TOKEN TABLE", flush=True)
    print("=" * 60, flush=True)
    
    try:
        await init_db()
        print("✓ Password reset token table created/verified", flush=True)
        print("=" * 60, flush=True)
    except Exception as e:
        print(f"✗ Error: {e}", flush=True)
        print("=" * 60, flush=True)
        raise

if __name__ == "__main__":
    asyncio.run(migrate_password_reset())

