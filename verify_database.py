"""
Verify that the database includes all latest changes
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine


async def verify_database():
    import sys
    def p(*args, **kwargs):
        print(*args, **kwargs)
        sys.stdout.flush()
    
    p("=" * 60)
    p("DATABASE SCHEMA VERIFICATION")
    p("=" * 60)
    
    async with engine.begin() as conn:
        # Check all tables
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        tables = [row[0] for row in result.fetchall()]
        p(f"\n✓ Total tables: {len(tables)}")
        p("  Tables:", ", ".join(tables))
        
        # Verify User table has new columns
        p("\n" + "-" * 60)
        p("USER TABLE VERIFICATION")
        p("-" * 60)
        result = await conn.execute(text("PRAGMA table_info(user)"))
        user_columns = {row[1]: row[2] for row in result.fetchall()}
        
        required_user_columns = {
            'id': 'INTEGER',
            'email': 'VARCHAR',
            'full_name': 'VARCHAR',
            'phone': 'VARCHAR',
            'address': 'VARCHAR',  # NEW
            'city': 'VARCHAR',      # NEW
            'zip_code': 'VARCHAR',  # NEW
            'country': 'VARCHAR',   # NEW
            'preferences': 'VARCHAR', # NEW
            'hashed_password': 'VARCHAR',
            'is_active': 'BOOLEAN',
            'is_superuser': 'BOOLEAN',
            'role': 'VARCHAR',
            'created_at': 'DATETIME',
            'updated_at': 'DATETIME',
        }
        
        p(f"  Total columns: {len(user_columns)}")
        missing = []
        for col, expected_type in required_user_columns.items():
            if col in user_columns:
                p(f"  ✓ {col}: {user_columns[col]}")
            else:
                p(f"  ✗ MISSING: {col}")
                missing.append(col)
        
        if missing:
            p(f"\n  ⚠ Missing columns: {', '.join(missing)}")
        else:
            p("\n  ✓ All required User columns present!")
        
        # Verify PaymentMethod table exists
        p("\n" + "-" * 60)
        p("PAYMENTMETHOD TABLE VERIFICATION")
        p("-" * 60)
        
        if 'paymentmethod' in tables:
            result = await conn.execute(text("PRAGMA table_info(paymentmethod)"))
            pm_columns = {row[1]: row[2] for row in result.fetchall()}
            
            required_pm_columns = {
                'id': 'INTEGER',
                'user_id': 'INTEGER',
                'card_type': 'VARCHAR',
                'last4': 'VARCHAR',
                'expiry_month': 'INTEGER',
                'expiry_year': 'INTEGER',
                'cardholder_name': 'VARCHAR',
                'is_default': 'BOOLEAN',
                'is_active': 'BOOLEAN',
                'card_token': 'VARCHAR',
                'created_at': 'DATETIME',
                'updated_at': 'DATETIME',
                'deleted_at': 'DATETIME',
            }
            
            p(f"  Total columns: {len(pm_columns)}")
            missing_pm = []
            for col, expected_type in required_pm_columns.items():
                if col in pm_columns:
                    p(f"  ✓ {col}: {pm_columns[col]}")
                else:
                    p(f"  ✗ MISSING: {col}")
                    missing_pm.append(col)
            
            if missing_pm:
                p(f"\n  ⚠ Missing columns: {', '.join(missing_pm)}")
            else:
                p("\n  ✓ PaymentMethod table is complete!")
        else:
            p("  ✗ PaymentMethod table NOT FOUND!")
        
        # Verify PreCheckIn table
        p("\n" + "-" * 60)
        p("PRECHECKIN TABLE VERIFICATION")
        p("-" * 60)
        if 'precheckin' in tables:
            result = await conn.execute(text("PRAGMA table_info(precheckin)"))
            pci_columns = {row[1] for row in result.fetchall()}
            p(f"  ✓ PreCheckIn table exists with {len(pci_columns)} columns")
        else:
            p("  ✗ PreCheckIn table NOT FOUND!")
        
        # Summary
        p("\n" + "=" * 60)
        p("VERIFICATION SUMMARY")
        p("=" * 60)
        
        all_good = True
        if missing:
            p(f"  ✗ User table missing: {', '.join(missing)}")
            all_good = False
        if 'paymentmethod' not in tables:
            p("  ✗ PaymentMethod table missing")
            all_good = False
        if missing_pm if 'paymentmethod' in tables else True:
            if 'paymentmethod' in tables and missing_pm:
                p(f"  ✗ PaymentMethod missing columns: {', '.join(missing_pm)}")
                all_good = False
        
        if all_good:
            p("  ✓ Database schema is up to date with all latest changes!")
        else:
            p("  ⚠ Some changes are missing. Run clear_and_rebuild.py again.")
        p("=" * 60)


if __name__ == "__main__":
    asyncio.run(verify_database())

