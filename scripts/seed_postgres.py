"""
Phase 1B — Seed PostgreSQL from JSON seed files.
Run: python scripts/seed_postgres.py
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DB_URL = (
    f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')} "
    f"dbname={os.getenv('POSTGRES_DB', 'ai_frontline_v2')} "
    f"user={os.getenv('POSTGRES_USER', 'admin')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'admin')}"
)

DATA_DIR = Path(__file__).parent.parent / "data" / "seeds"


def load(filename: str):
    with open(DATA_DIR / filename) as f:
        return json.load(f)


def seed_reps(cur, reps: list):
    rows = [(r["rep_id"], r["full_name"], r["gender"],
             r["email"], r["phone"], r["branch"], r["active"])
            for r in reps]
    execute_values(cur, """
        INSERT INTO sales_reps (rep_id, full_name, gender, email, phone, branch, active)
        VALUES %s ON CONFLICT (rep_id) DO NOTHING
    """, rows)
    print(f"  sales_reps: {len(rows)} rows")


def seed_customers(cur, customers: list):
    rows = [(
        c["customer_id"], c["full_name"], c.get("date_of_birth"),
        c.get("gender"), c.get("phone"), c.get("email"),
        c.get("national_id"), c.get("city"), c.get("occupation"),
        c.get("income_range"), c["segment"], c.get("kyc_status", "Pending"),
        c.get("credit_score"), c.get("loyalty_points", 0),
        c.get("relationship_since"), c.get("assigned_rep_id")
    ) for c in customers]
    execute_values(cur, """
        INSERT INTO customers (
            customer_id, full_name, date_of_birth, gender, phone, email,
            national_id, city, occupation, income_range, segment, kyc_status,
            credit_score, loyalty_points, relationship_since, assigned_rep_id
        ) VALUES %s ON CONFLICT (customer_id) DO NOTHING
    """, rows)
    print(f"  customers: {len(rows)} rows")


def seed_contracts(cur, contracts: list):
    contract_rows, clause_rows, coverage_rows = [], [], []

    for c in contracts:
        contract_rows.append((
            c["contract_id"], c["customer_id"], c["product_type"],
            c.get("product_id"), c["product_name"], c.get("status", "ACTIVE"),
            c.get("start_date"), c.get("end_date"),
            c.get("key_amount"), c.get("key_rate"),
            json.dumps(c.get("extra_fields", {}))
        ))

        for cl in c.get("clauses", []):
            clause_rows.append((
                cl["clause_id"], c["contract_id"],
                cl.get("clause_number"), cl.get("title"),
                cl.get("conditions"), cl.get("benefit"),
                cl.get("customer_qualifies"),
                cl.get("disqualification_reason"),
                json.dumps({k: v for k, v in cl.items()
                            if k not in ("clause_id", "clause_number", "title",
                                         "conditions", "benefit", "customer_qualifies",
                                         "disqualification_reason")})
            ))

        for cov in c.get("coverages", []):
            coverage_rows.append((
                cov["coverage_id"], c["contract_id"],
                cov.get("coverage_type"), cov.get("limit_amount"),
                cov.get("conditions")
            ))

    execute_values(cur, """
        INSERT INTO contracts (
            contract_id, customer_id, product_type, product_id, product_name,
            status, start_date, end_date, key_amount, key_rate, extra_fields
        ) VALUES %s ON CONFLICT (contract_id) DO NOTHING
    """, contract_rows)
    print(f"  contracts: {len(contract_rows)} rows")

    if clause_rows:
        execute_values(cur, """
            INSERT INTO contract_clauses (
                clause_id, contract_id, clause_number, title,
                conditions, benefit, customer_qualifies,
                disqualification_reason, extra_fields
            ) VALUES %s ON CONFLICT (clause_id) DO NOTHING
        """, clause_rows)
        print(f"  contract_clauses: {len(clause_rows)} rows")

    if coverage_rows:
        execute_values(cur, """
            INSERT INTO contract_coverages (
                coverage_id, contract_id, coverage_type, limit_amount, conditions
            ) VALUES %s ON CONFLICT (coverage_id) DO NOTHING
        """, coverage_rows)
        print(f"  contract_coverages: {len(coverage_rows)} rows")


def seed_products_held(cur, portfolio: dict):
    rows = [(cust_id, product_code)
            for cust_id, products in portfolio.items()
            for product_code in products]
    execute_values(cur, """
        INSERT INTO products_held (customer_id, product_code)
        VALUES %s ON CONFLICT DO NOTHING
    """, rows)
    print(f"  products_held: {len(rows)} rows")


def seed_transactions(cur, transactions: list):
    BATCH = 500
    total = 0
    for i in range(0, len(transactions), BATCH):
        batch = transactions[i:i + BATCH]
        rows = [(
            t["transaction_id"], t["customer_id"],
            t.get("account_id"), t["transaction_date"],
            t["amount"], t.get("type"),
            t.get("merchant_name"), t.get("merchant_category"),
            t.get("channel"), t.get("description"),
            t.get("status", "COMPLETED"), t.get("currency", "VND")
        ) for t in batch]
        execute_values(cur, """
            INSERT INTO transactions (
                transaction_id, customer_id, account_id, transaction_date,
                amount, type, merchant_name, merchant_category,
                channel, description, status, currency
            ) VALUES %s ON CONFLICT (transaction_id) DO NOTHING
        """, rows)
        total += len(rows)
    print(f"  transactions: {total} rows")


def main():
    print("Connecting to PostgreSQL...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    print("Seeding data...")
    try:
        seed_reps(cur, load("reps.json"))
        seed_customers(cur, load("customers.json"))
        seed_contracts(cur, load("contracts.json"))
        seed_products_held(cur, load("product_portfolio.json"))
        seed_transactions(cur, load("transactions.json"))
        conn.commit()
        print("\nDone.")
    except Exception as e:
        conn.rollback()
        print(f"\nError: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
