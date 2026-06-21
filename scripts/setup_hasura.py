"""
Phase 1F — Configure Hasura: track all tables, set up relationships,
           configure rep portfolio row-level permissions.
Run: python scripts/setup_hasura.py
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

HASURA_URL    = os.getenv("HASURA_URL", "http://localhost:8080/v1/graphql")
METADATA_URL  = HASURA_URL.replace("/v1/graphql", "/v1/metadata")
ADMIN_SECRET  = os.getenv("HASURA_ADMIN_SECRET", "hasura-admin-secret-2026")
HEADERS       = {"X-Hasura-Admin-Secret": ADMIN_SECRET, "Content-Type": "application/json"}

client = httpx.Client(timeout=30)


def run(payload: dict, label: str = ""):
    resp = client.post(METADATA_URL, json=payload, headers=HEADERS)
    data = resp.json()
    if "error" in data or (isinstance(data, dict) and data.get("code") not in (None, "already-exists", "already-tracked")):
        # Ignore "already exists" — idempotent
        if data.get("code") in ("already-exists", "already-tracked"):
            print(f"  (already exists) {label}")
        else:
            print(f"  ERROR {label}: {data}")
    else:
        print(f"  OK  {label}")
    return data


# ── 1. Track tables ──────────────────────────────────────────────────────────
TABLES = [
    "sales_reps",
    "customers",
    "contracts",
    "contract_clauses",
    "contract_coverages",
    "products_held",
    "transactions",
    "customer_memory",
]


def track_tables():
    print("\n[1] Tracking tables...")
    for table in TABLES:
        run({
            "type": "pg_track_table",
            "args": {
                "source": "default",
                "table":  {"schema": "public", "name": table},
            },
        }, f"track {table}")


# ── 2. Relationships ─────────────────────────────────────────────────────────
OBJECT_RELATIONSHIPS = [
    # table, relationship_name, local_col → foreign_col
    ("customers",         "rep",      "sales_reps",         "assigned_rep_id", "rep_id"),
    ("contracts",         "customer", "customers",          "customer_id",     "customer_id"),
    ("contract_clauses",  "contract", "contracts",          "contract_id",     "contract_id"),
    ("contract_coverages","contract", "contracts",          "contract_id",     "contract_id"),
    ("products_held",     "customer", "customers",          "customer_id",     "customer_id"),
    ("transactions",      "customer", "customers",          "customer_id",     "customer_id"),
    ("customer_memory",   "customer", "customers",          "customer_id",     "customer_id"),
]

ARRAY_RELATIONSHIPS = [
    # table, relationship_name, remote_table, remote_col → local_col
    ("customers",  "contracts",          "contracts",          "customer_id", "customer_id"),
    ("customers",  "contract_clauses",   "contract_clauses",  "contract_id", "contract_id"),  # via contracts — skip for now
    ("customers",  "products_held",      "products_held",     "customer_id", "customer_id"),
    ("customers",  "transactions",       "transactions",      "customer_id", "customer_id"),
    ("customers",  "memory",             "customer_memory",   "customer_id", "customer_id"),
    ("contracts",  "clauses",            "contract_clauses",  "contract_id", "contract_id"),
    ("contracts",  "coverages",          "contract_coverages","contract_id", "contract_id"),
    ("sales_reps", "customers",          "customers",         "assigned_rep_id", "rep_id"),
]


def track_relationships():
    print("\n[2] Creating object relationships...")
    for table, rel_name, remote_table, local_col, remote_col in OBJECT_RELATIONSHIPS:
        run({
            "type": "pg_create_object_relationship",
            "args": {
                "source": "default",
                "table":  {"schema": "public", "name": table},
                "name":   rel_name,
                "using":  {
                    "manual_configuration": {
                        "remote_table":    {"schema": "public", "name": remote_table},
                        "column_mapping":  {local_col: remote_col},
                    }
                },
            },
        }, f"{table}.{rel_name}")

    print("\n[3] Creating array relationships...")
    for table, rel_name, remote_table, remote_col, local_col in ARRAY_RELATIONSHIPS:
        if table == "customers" and rel_name == "contract_clauses":
            continue   # indirect — skip
        run({
            "type": "pg_create_array_relationship",
            "args": {
                "source": "default",
                "table":  {"schema": "public", "name": table},
                "name":   rel_name,
                "using":  {
                    "manual_configuration": {
                        "remote_table":   {"schema": "public", "name": remote_table},
                        "column_mapping": {local_col: remote_col},
                    }
                },
            },
        }, f"{table}.{rel_name}[]")


# ── 3. Permissions ───────────────────────────────────────────────────────────
def create_permissions():
    print("\n[4] Creating row-level permissions for role 'sales_rep'...")

    # customers — rep can only see their own portfolio
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "customers"},
            "role":   "sales_rep",
            "permission": {
                "columns":            "*",
                "filter":             {"assigned_rep_id": {"_eq": "X-Hasura-Rep-Id"}},
                "allow_aggregations": True,
            },
        },
    }, "customers SELECT (own portfolio only)")

    # contracts — via customer's rep_id
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "contracts"},
            "role":   "sales_rep",
            "permission": {
                "columns": "*",
                "filter":  {"customer": {"assigned_rep_id": {"_eq": "X-Hasura-Rep-Id"}}},
            },
        },
    }, "contracts SELECT (portfolio customers)")

    # contract_clauses
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "contract_clauses"},
            "role":   "sales_rep",
            "permission": {
                "columns": "*",
                "filter":  {"contract": {"customer": {"assigned_rep_id": {"_eq": "X-Hasura-Rep-Id"}}}},
            },
        },
    }, "contract_clauses SELECT")

    # contract_coverages
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "contract_coverages"},
            "role":   "sales_rep",
            "permission": {
                "columns": "*",
                "filter":  {"contract": {"customer": {"assigned_rep_id": {"_eq": "X-Hasura-Rep-Id"}}}},
            },
        },
    }, "contract_coverages SELECT")

    # transactions
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "transactions"},
            "role":   "sales_rep",
            "permission": {
                "columns": "*",
                "filter":  {"customer": {"assigned_rep_id": {"_eq": "X-Hasura-Rep-Id"}}},
                "limit":   200,
            },
        },
    }, "transactions SELECT (limit 200)")

    # products_held
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "products_held"},
            "role":   "sales_rep",
            "permission": {
                "columns": "*",
                "filter":  {"customer": {"assigned_rep_id": {"_eq": "X-Hasura-Rep-Id"}}},
            },
        },
    }, "products_held SELECT")

    # customer_memory
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "customer_memory"},
            "role":   "sales_rep",
            "permission": {
                "columns": "*",
                "filter":  {"customer": {"assigned_rep_id": {"_eq": "X-Hasura-Rep-Id"}}},
                "limit":   10,
            },
        },
    }, "customer_memory SELECT")

    # sales_reps — rep can only see themselves
    run({
        "type": "pg_create_select_permission",
        "args": {
            "source": "default",
            "table":  {"schema": "public", "name": "sales_reps"},
            "role":   "sales_rep",
            "permission": {
                "columns": "*",
                "filter":  {"rep_id": {"_eq": "X-Hasura-Rep-Id"}},
            },
        },
    }, "sales_reps SELECT (self only)")


# ── 4. Smoke test ─────────────────────────────────────────────────────────────
def smoke_test():
    print("\n[5] Smoke test — querying customer CUST-001 as admin...")
    resp = client.post(
        HASURA_URL,
        json={"query": """
            query {
              customers(where: {customer_id: {_eq: "CUST-001"}}) {
                customer_id full_name segment
                contracts(limit: 3) { contract_id product_name status }
                transactions(limit: 3, order_by: {transaction_date: desc}) {
                  transaction_id amount type
                }
              }
            }
        """},
        headers=HEADERS,
    )
    data = resp.json()
    if "errors" in data:
        print(f"  Smoke test ERROR: {data['errors']}")
    else:
        cust = data["data"]["customers"][0]
        print(f"  Customer: {cust['full_name']} ({cust['segment']})")
        print(f"  Contracts: {len(cust['contracts'])}")
        print(f"  Transactions: {len(cust['transactions'])}")
        print("  Smoke test passed ✅")


def main():
    print("Configuring Hasura...")
    track_tables()
    track_relationships()
    create_permissions()
    smoke_test()
    print("\nHasura setup complete.")


if __name__ == "__main__":
    main()
