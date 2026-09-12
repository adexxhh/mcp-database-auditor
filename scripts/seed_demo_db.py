"""
Script to seed a mock enterprise SaaS database with realistic data and anomalous charges.
"""

import asyncio
from datetime import datetime, timedelta
import os
import sys
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


DEFAULT_DB_FILE = "demo_saas.db"


async def seed_demo_database(db_url: Optional[str] = None) -> str:
    """
    Creates and populates a mock enterprise SaaS database.
    """
    if db_url is None:
        db_file = os.path.abspath(DEFAULT_DB_FILE)
        db_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        # Enable Foreign Keys for SQLite
        if "sqlite" in db_url:
            await conn.execute(text("PRAGMA foreign_keys = ON;"))

        # Drop existing tables
        tables = ["audit_events", "transactions", "invoices", "users", "tenants"]
        for tbl in tables:
            await conn.execute(text(f"DROP TABLE IF EXISTS {tbl};"))

        # 1. Create tenants table
        await conn.execute(
            text(
                """
                CREATE TABLE tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    domain TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        )

        # 2. Create users table
        await conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL DEFAULT 'MEMBER',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );
                """
            )
        )

        # 3. Create invoices table
        await conn.execute(
            text(
                """
                CREATE TABLE invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount DECIMAL(12, 2) NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PAID',
                    due_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
        )

        # 4. Create transactions table
        await conn.execute(
            text(
                """
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id INTEGER NOT NULL,
                    tenant_id INTEGER NOT NULL,
                    amount DECIMAL(12, 2) NOT NULL,
                    status TEXT NOT NULL DEFAULT 'SUCCESS',
                    payment_method TEXT NOT NULL,
                    flags TEXT,
                    transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );
                """
            )
        )

        # 5. Create audit_events table
        await conn.execute(
            text(
                """
                CREATE TABLE audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    ip_address TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
        )

        # Create Indexes
        await conn.execute(text("CREATE INDEX idx_users_tenant ON users(tenant_id);"))
        await conn.execute(text("CREATE INDEX idx_invoices_tenant ON invoices(tenant_id);"))
        await conn.execute(text("CREATE INDEX idx_transactions_invoice ON transactions(invoice_id);"))
        await conn.execute(text("CREATE INDEX idx_audit_tenant_user ON audit_events(tenant_id, user_id);"))

        # Populate Data
        # Tenants
        await conn.execute(
            text(
                """
                INSERT INTO tenants (name, domain, status) VALUES
                ('Acme Corp', 'acme.com', 'ACTIVE'),
                ('Stark Industries', 'stark.io', 'ACTIVE'),
                ('Cyberdyne Systems', 'cyberdyne.net', 'SUSPENDED'),
                ('Wayne Enterprises', 'wayne.com', 'ACTIVE');
                """
            )
        )

        # Users
        await conn.execute(
            text(
                """
                INSERT INTO users (tenant_id, name, email, role) VALUES
                (1, 'Alice Smith', 'alice@acme.com', 'ADMIN'),
                (1, 'Bob Jones', 'bob@acme.com', 'MEMBER'),
                (2, 'Tony Stark', 'tony@stark.io', 'ADMIN'),
                (2, 'Pepper Potts', 'pepper@stark.io', 'FINANCE'),
                (3, 'Miles Dyson', 'miles@cyberdyne.net', 'ADMIN'),
                (4, 'Bruce Wayne', 'bruce@wayne.com', 'ADMIN'),
                (4, 'Lucius Fox', 'lucius@wayne.com', 'FINANCE');
                """
            )
        )

        # Invoices
        await conn.execute(
            text(
                """
                INSERT INTO invoices (tenant_id, user_id, amount, status, due_date) VALUES
                (1, 1, 1500.00, 'PAID', '2026-01-15'),
                (1, 2, 49.99, 'PAID', '2026-02-01'),
                (2, 3, 50000.00, 'PAID', '2026-02-10'),
                (2, 4, 120000.00, 'OVERDUE', '2026-03-01'),
                (3, 5, 2500000.00, 'FLAGGED', '2026-01-01'),
                (4, 6, 999999.99, 'PAID', '2026-02-28'),
                (4, 7, 350.00, 'PAID', '2026-03-05');
                """
            )
        )

        # Transactions (including simulated anomalous charges)
        await conn.execute(
            text(
                """
                INSERT INTO transactions (invoice_id, tenant_id, amount, status, payment_method, flags) VALUES
                (1, 1, 1500.00, 'SUCCESS', 'CREDIT_CARD', 'NORMAL'),
                (2, 1, 49.99, 'SUCCESS', 'CREDIT_CARD', 'NORMAL'),
                (3, 2, 50000.00, 'SUCCESS', 'WIRE_TRANSFER', 'NORMAL'),
                (4, 2, 120000.00, 'FAILED', 'ACH', 'INSUFFICIENT_FUNDS'),
                (5, 3, 2500000.00, 'FLAGGED', 'CRYPTO', 'ANOMALOUS_HIGH_AMOUNT_UNVERIFIED'),
                (6, 4, 999999.99, 'SUCCESS', 'WIRE_TRANSFER', 'SUSPICIOUS_OFFSHORE_ROUTE'),
                (7, 4, -5000.00, 'REFUNDED', 'CREDIT_CARD', 'ANOMALOUS_NEGATIVE_CHARGE');
                """
            )
        )

        # Audit Events
        await conn.execute(
            text(
                """
                INSERT INTO audit_events (tenant_id, user_id, action, ip_address) VALUES
                (1, 1, 'USER_LOGIN', '192.168.1.10'),
                (1, 2, 'INVOICE_VIEW', '192.168.1.15'),
                (2, 3, 'API_KEY_CREATED', '10.0.0.1'),
                (2, 4, 'PAYMENT_SUBMITTED', '10.0.0.5'),
                (3, 5, 'UNAUTHORIZED_EXPORT_ATTEMPT', '198.51.100.42'),
                (4, 6, 'ADMIN_PRIVILEGE_ESCALATION', '172.16.0.1');
                """
            )
        )

    await engine.dispose()
    return db_url


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_FILE
    target_url = f"sqlite+aiosqlite:///{os.path.abspath(db_path)}"
    print(f"Seeding mock SaaS database at: {target_url}...")
    asyncio.run(seed_demo_database(target_url))
    print("Database seeding completed successfully.")
