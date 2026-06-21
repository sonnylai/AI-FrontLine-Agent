"""
Phase 1C — Seed Neo4j: build the contract knowledge graph.
Nodes: Customer, Contract, Clause, Coverage, Condition
Run: python scripts/seed_neo4j.py
"""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
USER     = os.getenv("NEO4J_USER",     "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "Frontline2026@Xyz")

DATA_DIR = Path(__file__).parent.parent / "data" / "seeds"

# Clause conditions that apply across all contracts of the same type.
# Shared Condition nodes so we can query "which customers satisfy condition X"
# without duplicating logic per contract.
SHARED_CONDITIONS = [
    {
        "condition_id":   "COND-7.3-TENURE",
        "type":           "TENURE",
        "description":    "Hợp đồng liên tục >= 12 tháng",
        "threshold":      12,
        "unit":           "months",
    },
    {
        "condition_id":   "COND-7.3-SEGMENT",
        "type":           "SEGMENT",
        "description":    "Phân khúc Gold, Platinum, hoặc Elite",
        "allowed_values": ["Gold", "Platinum", "Elite"],
    },
    {
        "condition_id":   "COND-LOAN-KYC",
        "type":           "KYC",
        "description":    "KYC status Verified",
        "allowed_values": ["Verified"],
    },
    {
        "condition_id":   "COND-BANCA-ACTIVE",
        "type":           "CONTRACT_STATUS",
        "description":    "Hợp đồng đang trong trạng thái ACTIVE",
        "allowed_values": ["ACTIVE"],
    },
]

# Map clause_number → condition_ids it requires
CLAUSE_CONDITIONS = {
    "7.3": ["COND-7.3-TENURE", "COND-7.3-SEGMENT"],
    "6.1": ["COND-BANCA-ACTIVE"],
    "6.2": ["COND-BANCA-ACTIVE"],
    "6.3": ["COND-BANCA-ACTIVE"],
}


def load(filename: str):
    with open(DATA_DIR / filename) as f:
        return json.load(f)


def clean(value):
    """Return None for empty strings, pass through everything else."""
    if value == "":
        return None
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Constraint & index setup
# ─────────────────────────────────────────────────────────────────────────────
def create_constraints(session):
    constraints = [
        "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (n:Customer) REQUIRE n.customer_id IS UNIQUE",
        "CREATE CONSTRAINT contract_id IF NOT EXISTS FOR (n:Contract) REQUIRE n.contract_id IS UNIQUE",
        "CREATE CONSTRAINT clause_id   IF NOT EXISTS FOR (n:Clause)   REQUIRE n.clause_id   IS UNIQUE",
        "CREATE CONSTRAINT coverage_id IF NOT EXISTS FOR (n:Coverage) REQUIRE n.coverage_id IS UNIQUE",
        "CREATE CONSTRAINT condition_id IF NOT EXISTS FOR (n:Condition) REQUIRE n.condition_id IS UNIQUE",
    ]
    for c in constraints:
        session.run(c)
    print("  Constraints created")


# ─────────────────────────────────────────────────────────────────────────────
# Node seeders
# ─────────────────────────────────────────────────────────────────────────────
def seed_conditions(session):
    for cond in SHARED_CONDITIONS:
        session.run("""
            MERGE (cn:Condition {condition_id: $condition_id})
            SET cn.type        = $type,
                cn.description = $description,
                cn.threshold   = $threshold,
                cn.unit        = $unit,
                cn.allowed_values = $allowed_values
        """, {
            "condition_id":   cond["condition_id"],
            "type":           cond["type"],
            "description":    cond["description"],
            "threshold":      cond.get("threshold"),
            "unit":           cond.get("unit"),
            "allowed_values": cond.get("allowed_values", []),
        })
    print(f"  Condition nodes: {len(SHARED_CONDITIONS)}")


def seed_customers(session, customers: list):
    for c in customers:
        session.run("""
            MERGE (cu:Customer {customer_id: $customer_id})
            SET cu.full_name          = $full_name,
                cu.segment            = $segment,
                cu.credit_score       = $credit_score,
                cu.kyc_status         = $kyc_status,
                cu.loyalty_points     = $loyalty_points,
                cu.city               = $city,
                cu.income_range       = $income_range,
                cu.assigned_rep_id    = $assigned_rep_id
        """, {
            "customer_id":      c["customer_id"],
            "full_name":        c["full_name"],
            "segment":          c["segment"],
            "credit_score":     c.get("credit_score"),
            "kyc_status":       c.get("kyc_status"),
            "loyalty_points":   c.get("loyalty_points", 0),
            "city":             c.get("city"),
            "income_range":     c.get("income_range"),
            "assigned_rep_id":  c.get("assigned_rep_id"),
        })
    print(f"  Customer nodes: {len(customers)}")


def seed_contracts_and_edges(session, contracts: list, customers: list):
    customer_map = {c["customer_id"]: c for c in customers}
    clause_count = coverage_count = edge_count = 0

    for ct in contracts:
        # Contract node
        session.run("""
            MERGE (ct:Contract {contract_id: $contract_id})
            SET ct.product_type  = $product_type,
                ct.product_name  = $product_name,
                ct.status        = $status,
                ct.start_date    = $start_date,
                ct.end_date      = $end_date,
                ct.key_amount    = $key_amount,
                ct.key_rate      = $key_rate,
                ct.extra_fields  = $extra_fields
        """, {
            "contract_id":  ct["contract_id"],
            "product_type": ct["product_type"],
            "product_name": ct["product_name"],
            "status":       ct.get("status", "ACTIVE"),
            "start_date":   clean(ct.get("start_date")),
            "end_date":     clean(ct.get("end_date")),
            "key_amount":   ct.get("key_amount"),
            "key_rate":     ct.get("key_rate"),
            "extra_fields": json.dumps(ct.get("extra_fields", {})),
        })

        # (Customer)-[:HAS_CONTRACT]->(Contract)
        session.run("""
            MATCH (cu:Customer {customer_id: $customer_id})
            MATCH (ct:Contract {contract_id: $contract_id})
            MERGE (cu)-[:HAS_CONTRACT {since: $since}]->(ct)
        """, {
            "customer_id": ct["customer_id"],
            "contract_id": ct["contract_id"],
            "since":       clean(ct.get("start_date")),
        })
        edge_count += 1

        # Clause nodes + (Contract)-[:HAS_CLAUSE]->(Clause)
        for cl in ct.get("clauses", []):
            session.run("""
                MERGE (cl:Clause {clause_id: $clause_id})
                SET cl.clause_number           = $clause_number,
                    cl.title                   = $title,
                    cl.conditions              = $conditions,
                    cl.benefit                 = $benefit,
                    cl.customer_qualifies      = $customer_qualifies,
                    cl.disqualification_reason = $disqualification_reason
            """, {
                "clause_id":               cl["clause_id"],
                "clause_number":           cl.get("clause_number"),
                "title":                   cl.get("title"),
                "conditions":              cl.get("conditions"),
                "benefit":                 cl.get("benefit"),
                "customer_qualifies":      cl.get("customer_qualifies"),
                "disqualification_reason": cl.get("disqualification_reason"),
            })

            session.run("""
                MATCH (ct:Contract {contract_id: $contract_id})
                MATCH (cl:Clause   {clause_id:   $clause_id})
                MERGE (ct)-[:HAS_CLAUSE]->(cl)
            """, {"contract_id": ct["contract_id"], "clause_id": cl["clause_id"]})

            # Link Clause → Condition (REQUIRES)
            for cond_id in CLAUSE_CONDITIONS.get(cl.get("clause_number", ""), []):
                session.run("""
                    MATCH (cl:Clause    {clause_id:    $clause_id})
                    MATCH (cn:Condition {condition_id: $condition_id})
                    MERGE (cl)-[:REQUIRES]->(cn)
                """, {"clause_id": cl["clause_id"], "condition_id": cond_id})

            clause_count += 1

        # Coverage nodes + (Contract)-[:HAS_COVERAGE]->(Coverage)
        for cov in ct.get("coverages", []):
            session.run("""
                MERGE (cov:Coverage {coverage_id: $coverage_id})
                SET cov.coverage_type = $coverage_type,
                    cov.limit_amount  = $limit_amount,
                    cov.conditions    = $conditions
            """, {
                "coverage_id":   cov["coverage_id"],
                "coverage_type": cov.get("coverage_type"),
                "limit_amount":  cov.get("limit_amount"),
                "conditions":    cov.get("conditions"),
            })

            session.run("""
                MATCH (ct:Contract  {contract_id:  $contract_id})
                MATCH (cov:Coverage {coverage_id:  $coverage_id})
                MERGE (ct)-[:HAS_COVERAGE]->(cov)
            """, {"contract_id": ct["contract_id"], "coverage_id": cov["coverage_id"]})
            coverage_count += 1

    print(f"  Contract nodes:    {len(contracts)}")
    print(f"  HAS_CONTRACT edges:{edge_count}")
    print(f"  Clause nodes:      {clause_count}")
    print(f"  Coverage nodes:    {coverage_count}")


def seed_satisfies_edges(session, customers: list, contracts: list):
    """
    Pre-evaluate each customer against each shared Condition.
    Stores result on the SATISFIES relationship so agents can query instantly.
    """
    # Build tenure map: customer_id → max continuous_months across BANCASSURANCE contracts
    tenure_map: dict[str, int] = {}
    for ct in contracts:
        if ct["product_type"] == "BANCASSURANCE":
            months = ct.get("extra_fields", {}).get("continuous_months", 0)
            cid = ct["customer_id"]
            tenure_map[cid] = max(tenure_map.get(cid, 0), months)

    count = 0
    for c in customers:
        cid = c["customer_id"]
        segment = c["segment"]
        kyc = c.get("kyc_status", "")

        evaluations = {
            "COND-7.3-TENURE":  (tenure_map.get(cid, 0), tenure_map.get(cid, 0) >= 12),
            "COND-7.3-SEGMENT": (segment, segment in ["Gold", "Platinum", "Elite"]),
            "COND-LOAN-KYC":    (kyc,     kyc == "Verified"),
            "COND-BANCA-ACTIVE": ("ACTIVE", True),
        }

        for cond_id, (value, result) in evaluations.items():
            session.run("""
                MATCH (cu:Customer  {customer_id:  $customer_id})
                MATCH (cn:Condition {condition_id: $condition_id})
                MERGE (cu)-[r:SATISFIES]->(cn)
                SET r.value = $value, r.result = $result
            """, {
                "customer_id":  cid,
                "condition_id": cond_id,
                "value":        str(value),
                "result":       result,
            })
            count += 1

    print(f"  SATISFIES edges:   {count}")


def print_summary(session):
    result = session.run("""
        MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt
        ORDER BY cnt DESC
    """)
    print("\n  Graph summary:")
    for row in result:
        print(f"    {row['label']:<15} {row['cnt']} nodes")

    result = session.run("""
        MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt
        ORDER BY cnt DESC
    """)
    for row in result:
        print(f"    {row['rel']:<20} {row['cnt']} edges")


def main():
    print("Connecting to Neo4j...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    driver.verify_connectivity()

    customers = load("customers.json")
    contracts = load("contracts.json")

    with driver.session() as session:
        print("Creating constraints...")
        create_constraints(session)

        print("Seeding nodes...")
        seed_conditions(session)
        seed_customers(session, customers)
        seed_contracts_and_edges(session, contracts, customers)

        print("Evaluating customer conditions (SATISFIES edges)...")
        seed_satisfies_edges(session, customers, contracts)

        print_summary(session)

    driver.close()
    print("\nNeo4j seed complete.")


if __name__ == "__main__":
    main()
