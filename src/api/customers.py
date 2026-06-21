from fastapi import APIRouter, Depends, HTTPException, status
from src.db import hasura_client
from src.middleware.jwt_auth import get_current_rep
from src.models.customer import Customer360, Contract, Transaction, SalesRep

router = APIRouter(prefix="/customer", tags=["customers"])

CUSTOMER_360_QUERY = """
query Customer360($customer_id: String!, $rep_id: String!) {
  customers(where: {customer_id: {_eq: $customer_id}, assigned_rep_id: {_eq: $rep_id}}) {
    customer_id
    full_name
    segment
    kyc_status
    credit_score
    loyalty_points
    city
    occupation
    income_range
    relationship_since
    rep {
      rep_id
      full_name
      email
      branch
    }
    products_held {
      product_code
    }
    contracts(order_by: {start_date: desc}) {
      contract_id
      product_type
      product_name
      status
      start_date
      end_date
      key_amount
      extra_fields
    }
    transactions(limit: 20, order_by: {transaction_date: desc}) {
      transaction_id
      transaction_date
      amount
      type
      merchant_name
      merchant_category
      description
      status
    }
  }
}
"""


@router.get("/{customer_id}", response_model=Customer360)
async def get_customer_360(customer_id: str, rep: dict = Depends(get_current_rep)):
    data = await hasura_client.query(CUSTOMER_360_QUERY, {"customer_id": customer_id, "rep_id": rep["sub"]})
    rows = data.get("customers", [])

    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found or not in your portfolio")

    row = rows[0]
    rep_data = row.get("rep")

    return Customer360(
        customer_id=row["customer_id"],
        full_name=row["full_name"],
        segment=row["segment"],
        kyc_status=row["kyc_status"],
        credit_score=row.get("credit_score"),
        loyalty_points=row.get("loyalty_points", 0),
        city=row.get("city"),
        occupation=row.get("occupation"),
        income_range=row.get("income_range"),
        relationship_since=str(row["relationship_since"]) if row.get("relationship_since") else None,
        products_held=[p["product_code"] for p in row.get("products_held", [])],
        contracts=[
            Contract(
                contract_id=c["contract_id"],
                product_type=c["product_type"],
                product_name=c["product_name"],
                status=c["status"],
                start_date=str(c["start_date"]) if c.get("start_date") else None,
                end_date=str(c["end_date"]) if c.get("end_date") else None,
                key_amount=c.get("key_amount"),
                extra_fields=c.get("extra_fields"),
            )
            for c in row.get("contracts", [])
        ],
        recent_transactions=[
            Transaction(
                transaction_id=t["transaction_id"],
                transaction_date=str(t["transaction_date"]),
                amount=t["amount"],
                type=t["type"],
                merchant_name=t.get("merchant_name"),
                merchant_category=t.get("merchant_category"),
                description=t.get("description"),
                status=t.get("status", "COMPLETED"),
            )
            for t in row.get("transactions", [])
        ],
        rep=SalesRep(
            rep_id=rep_data["rep_id"],
            full_name=rep_data["full_name"],
            email=rep_data["email"],
            branch=rep_data.get("branch"),
        ) if rep_data else None,
    )
