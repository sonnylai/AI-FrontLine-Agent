"""
Node 2 — QueryDispatcher: fetches full customer 360 from Hasura GraphQL.
Result is stored in state["customer_360"] for all agents to read.
"""
from src.agents.state import AgentState
from src.db import hasura_client

_QUERY = """
query Customer360($id: String!) {
  customers(where: {customer_id: {_eq: $id}}) {
    customer_id full_name segment kyc_status
    credit_score loyalty_points city occupation income_range relationship_since
    assigned_rep_id
    rep { rep_id full_name branch }
    products_held { product_code }
    contracts(order_by: {start_date: desc}) {
      contract_id product_type product_name status
      start_date end_date key_amount key_rate extra_fields
      clauses {
        clause_id clause_number title benefit
        customer_qualifies disqualification_reason
      }
      coverages { coverage_id coverage_type limit_amount conditions }
    }
    transactions(limit: 20, order_by: {transaction_date: desc}) {
      transaction_id transaction_date amount type
      merchant_name merchant_category description status
    }
    memory(limit: 5, order_by: {session_date: desc}) {
      session_date summary key_concerns products_discussed sentiment
    }
  }
}
"""


async def run(state: AgentState) -> dict:
    data = await hasura_client.query(_QUERY, {"id": state["customer_id"]})
    rows = data.get("customers", [])
    customer_360 = rows[0] if rows else {}
    return {"customer_360": customer_360}
