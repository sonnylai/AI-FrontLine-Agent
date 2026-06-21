"""
QueryDispatcher — pure Python, no LLM.
Handles TRANSACTION_QUERY intents by executing named Hasura GraphQL templates.

Receives query_type + query_params from its fan-out branch state (set by _fan_out
from the IntentRewrite sub_questions list). Params contain resolved values —
dates are already concrete strings (IntentRewrite resolves "3 months ago" → dates).

Cache: Redis query:{customer_id}:{query_type}:{params_hash} with tiered TTL.
verified=True always — data is deterministic from Postgres, no hallucination risk.
See MEMORY_SCHEMA.md §3 and §6 for template reference.
"""
import hashlib
import json

from langsmith import traceable
from src.agents.state import AgentState, AgentResult
from src.cache import redis_client
from src.db import hasura_client


def _to_ts(date_str: str) -> str:
    """Convert YYYY-MM-DD → YYYY-MM-DDT00:00:00 for timestamptz column comparison.
    If already has a time component, return as-is."""
    if date_str and "T" not in date_str:
        return f"{date_str}T00:00:00"
    return date_str

# ── Tiered TTL per query_type (see MEMORY_SCHEMA.md §3) ──────────────────────
_TTL: dict[str, int] = {
    "profile_demographics":       redis_client.TTL_QUERY_LONG,   # 24h
    "product_portfolio_summary":  redis_client.TTL_QUERY_LONG,   # 24h
    "insurance_contract_status":  redis_client.TTL_QUERY_MED,    # 6h
    "term_deposit_list":          redis_client.TTL_QUERY_MED,    # 6h
    "loan_balance_remaining":     redis_client.TTL_QUERY_MED,    # 6h
    "segment_gap_analysis":       redis_client.TTL_QUERY_MED,    # 6h
    "aggregate_by_category":      redis_client.TTL_QUERY_SHORT,  # 30min
    "aggregate_by_merchant":      redis_client.TTL_QUERY_SHORT,  # 30min
    "transaction_count_by_period": redis_client.TTL_QUERY_SHORT, # 30min
    "casa_balance_summary":       redis_client.TTL_QUERY_SHORT,  # 30min
}

# ── GraphQL templates ─────────────────────────────────────────────────────────

_Q_PROFILE = """
query Profile($cid: String!) {
  customers(where: {customer_id: {_eq: $cid}}) {
    income_range occupation kyc_status credit_score
    loyalty_points city relationship_since
  }
}"""

_Q_PORTFOLIO = """
query Portfolio($cid: String!) {
  customers(where: {customer_id: {_eq: $cid}}) {
    products_held { product_code }
    contracts(order_by: {start_date: desc}) {
      contract_id product_type product_name status start_date end_date key_amount
    }
  }
}"""

_Q_AGG_CATEGORY = """
query AggCategory($cid: String!, $from: timestamptz!, $to: timestamptz!) {
  transactions(
    where: {customer_id: {_eq: $cid}, transaction_date: {_gte: $from, _lte: $to}}
  ) {
    merchant_category
    amount
  }
}"""

# Filter by specific merchant name (e.g. "booking.com") — uses ilike for partial/case-insensitive match
_Q_AGG_MERCHANT_BY_NAME = """
query AggMerchantByName($cid: String!, $from: timestamptz!, $to: timestamptz!, $name: String!) {
  transactions(
    where: {
      customer_id:   {_eq: $cid}
      transaction_date: {_gte: $from, _lte: $to}
      merchant_name: {_ilike: $name}
    }
    order_by: {transaction_date: desc}
  ) {
    merchant_name merchant_category amount transaction_date description status
  }
}"""

# Filter by merchant category (e.g. "F&B", "SHOPPING") — used when no specific merchant is named
_Q_AGG_MERCHANT_BY_CAT = """
query AggMerchantByCat($cid: String!, $from: timestamptz!, $to: timestamptz!, $cat: String!) {
  transactions(
    where: {
      customer_id:       {_eq: $cid}
      transaction_date:  {_gte: $from, _lte: $to}
      merchant_category: {_eq: $cat}
    }
  ) {
    merchant_name merchant_category amount transaction_date
  }
}"""

_Q_TXN_COUNT = """
query TxnCount($cid: String!, $from: timestamptz!, $to: timestamptz!) {
  transactions_aggregate(
    where: {customer_id: {_eq: $cid}, transaction_date: {_gte: $from, _lte: $to}}
  ) {
    aggregate { count }
  }
}"""

_Q_CASA = """
query Casa($cid: String!) {
  accounts(where: {customer_id: {_eq: $cid}, account_type: {_in: ["CASA","SAVINGS"]}}) {
    account_id account_type balance currency last_updated
  }
}"""

_Q_LOAN = """
query Loan($cid: String!) {
  loan_accounts(where: {customer_id: {_eq: $cid}, status: {_eq: "ACTIVE"}}) {
    loan_id product_name original_amount outstanding_balance
    monthly_installment next_payment_date maturity_date
  }
}"""

_Q_TERM_DEPOSIT = """
query TermDeposit($cid: String!) {
  term_deposits(where: {customer_id: {_eq: $cid}}) {
    deposit_id product_name principal_amount interest_rate
    start_date maturity_date status
  }
}"""

_Q_INSURANCE = """
query Insurance($cid: String!) {
  contracts(
    where: {customer_id: {_eq: $cid}, product_type: {_eq: "INSURANCE"}}
    order_by: {start_date: desc}
  ) {
    contract_id product_name status start_date end_date key_amount
  }
}"""


# ── NBA gap analysis (no Hasura — derived from minimal state) ─────────────────

_NBA_RULES: dict[str, list[str]] = {
    "Standard": ["CASA", "DEBIT"],
    "Silver":   ["CREDIT_GOLD", "TERM_DEPOSIT", "PERSONAL_ACCIDENT"],
    "Gold":     ["BANCASSURANCE", "CREDIT_PLATINUM", "CERTIFICATE_OF_DEPOSIT"],
    "Platinum": ["BANCASSURANCE", "BUSINESS_LENDING", "VIP_PRIORITY"],
    "Elite":    ["BANCASSURANCE", "BUSINESS_LENDING", "VIP_PRIORITY", "CERTIFICATE_OF_DEPOSIT"],
}


# ── Result formatters ─────────────────────────────────────────────────────────

def _fmt_profile(data: dict) -> str:
    rows = data.get("customers", [{}])
    r = rows[0] if rows else {}
    return (
        f"Thông tin hồ sơ khách hàng:\n"
        f"  Dải thu nhập: {r.get('income_range', 'N/A')}\n"
        f"  Nghề nghiệp:  {r.get('occupation', 'N/A')}\n"
        f"  KYC:          {r.get('kyc_status', 'N/A')}\n"
        f"  Credit score: {r.get('credit_score', 'N/A')}\n"
        f"  Điểm tích lũy:{r.get('loyalty_points', 0):,}\n"
        f"  Thành phố:    {r.get('city', 'N/A')}\n"
        f"  KH từ:        {r.get('relationship_since', 'N/A')}"
    )


def _fmt_portfolio(data: dict) -> str:
    rows = data.get("customers", [{}])
    r = rows[0] if rows else {}
    held = [p["product_code"] for p in r.get("products_held", [])]
    contracts = r.get("contracts", [])
    lines = [f"Danh mục sản phẩm: {', '.join(held) or 'Chưa có'}"]
    if contracts:
        lines.append(f"\nHợp đồng ({len(contracts)}):")
        for c in contracts:
            lines.append(
                f"  {c['product_name']} ({c['contract_id']}): "
                f"{c['status']} | {c.get('start_date','?')} → {c.get('end_date','?')}"
            )
    return "\n".join(lines)


def _fmt_agg_category(data: dict, date_from: str, date_to: str) -> str:
    txns = data.get("transactions", [])
    cats: dict[str, float] = {}
    for t in txns:
        cat = t.get("merchant_category", "OTHER")
        cats[cat] = cats.get(cat, 0) + abs(t.get("amount", 0))
    sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)
    lines = [f"Chi tiêu theo danh mục ({date_from} → {date_to}):"]
    for cat, amt in sorted_cats:
        lines.append(f"  {cat}: {amt:,.0f} VND")
    lines.append(f"  Tổng: {sum(cats.values()):,.0f} VND")
    return "\n".join(lines)


def _fmt_agg_merchant_by_name(data: dict, merchant_name: str, date_from: str, date_to: str) -> str:
    txns = data.get("transactions", [])
    if not txns:
        return f"Không tìm thấy giao dịch nào với '{merchant_name}' trong khoảng {date_from[:10]} → {date_to[:10]}."
    total = sum(abs(t.get("amount", 0)) for t in txns)
    lines = [
        f"Giao dịch với {merchant_name} ({date_from[:10]} → {date_to[:10]}): "
        f"{len(txns)} giao dịch"
    ]
    for t in txns[:15]:
        lines.append(
            f"  {t.get('transaction_date','?')[:10]}: {abs(t.get('amount', 0)):,.0f} VND"
            f" — {t.get('description') or t.get('merchant_name', '?')}"
            f" [{t.get('status', '')}]"
        )
    lines.append(f"  Tổng: {total:,.0f} VND")
    return "\n".join(lines)


def _fmt_agg_merchant_by_cat(data: dict, date_from: str, date_to: str) -> str:
    txns = data.get("transactions", [])
    merchants: dict[str, float] = {}
    for t in txns:
        m = t.get("merchant_name") or t.get("merchant_category", "Unknown")
        merchants[m] = merchants.get(m, 0) + abs(t.get("amount", 0))
    sorted_m = sorted(merchants.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = [f"Chi tiêu theo merchant ({date_from[:10]} → {date_to[:10]}):"]
    for m, amt in sorted_m:
        lines.append(f"  {m}: {amt:,.0f} VND")
    return "\n".join(lines)


def _fmt_txn_count(data: dict, date_from: str, date_to: str) -> str:
    count = data.get("transactions_aggregate", {}).get("aggregate", {}).get("count", 0)
    return f"Số giao dịch từ {date_from} đến {date_to}: {count} giao dịch"


def _fmt_casa(data: dict) -> str:
    accounts = data.get("accounts", [])
    if not accounts:
        return "Không tìm thấy tài khoản CASA."
    lines = ["Số dư tài khoản:"]
    for a in accounts:
        lines.append(
            f"  {a['account_type']} ({a['account_id']}): "
            f"{a['balance']:,.0f} {a.get('currency','VND')}"
        )
    return "\n".join(lines)


def _fmt_loan(data: dict) -> str:
    loans = data.get("loan_accounts", [])
    if not loans:
        return "Khách hàng không có khoản vay đang hoạt động."
    lines = ["Dư nợ vay còn lại:"]
    for l in loans:
        lines.append(
            f"  {l['product_name']}: còn {l['outstanding_balance']:,.0f} VND"
            f" | Trả/tháng: {l.get('monthly_installment',0):,.0f} VND"
            f" | Đến: {l.get('maturity_date','N/A')}"
        )
    return "\n".join(lines)


def _fmt_term_deposit(data: dict) -> str:
    deposits = data.get("term_deposits", [])
    if not deposits:
        return "Khách hàng không có tiền gửi có kỳ hạn."
    lines = ["Tiền gửi có kỳ hạn:"]
    for d in deposits:
        lines.append(
            f"  {d['product_name']}: {d['principal_amount']:,.0f} VND"
            f" @ {d['interest_rate']}%"
            f" | {d['start_date']} → {d['maturity_date']} ({d['status']})"
        )
    return "\n".join(lines)


def _fmt_insurance(data: dict) -> str:
    contracts = data.get("contracts", [])
    if not contracts:
        return "Khách hàng không có hợp đồng bảo hiểm."
    lines = ["Hợp đồng bảo hiểm:"]
    for c in contracts:
        lines.append(
            f"  {c['product_name']} ({c['contract_id']}): {c['status']}"
            f" | {c.get('start_date','?')} → {c.get('end_date','?')}"
            + (f" | {c['key_amount']:,.0f} VND" if c.get('key_amount') else "")
        )
    return "\n".join(lines)


def _fmt_segment_gap(customer_360: dict) -> str:
    segment  = customer_360.get("segment", "Standard")
    held     = set(customer_360.get("products_held", []))
    expected = _NBA_RULES.get(segment, [])
    gaps     = [p for p in expected if p not in held]
    return (
        f"Phân tích phân khúc {segment}:\n"
        f"  Đang có: {', '.join(held) or 'Chưa có'}\n"
        f"  Còn thiếu theo phân khúc: {', '.join(gaps) or 'Đã đủ cơ bản'}"
    )


# ── Public entry point ────────────────────────────────────────────────────────

async def run(state: AgentState) -> dict:
    customer_id  = state["customer_id"]
    customer_360 = state.get("customer_360", {})
    query_type   = state.get("query_type") or "profile_demographics"
    params       = state.get("query_params") or {}

    # Redis cache key includes params hash for parameterised queries
    params_hash = hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cache_key   = redis_client.key_query(customer_id, query_type, params_hash)
    ttl         = _TTL.get(query_type, redis_client.TTL_QUERY_MED)

    cached = await redis_client.get(cache_key)
    if cached:
        answer = cached if isinstance(cached, str) else json.dumps(cached, ensure_ascii=False)
    else:
        answer = await _execute(query_type, params, customer_id, customer_360)
        await redis_client.set(cache_key, answer, ttl=ttl)

    result: AgentResult = {
        "agent":    "query_dispatcher",
        "answer":   answer,
        "sources":  [f"hasura:{query_type}"],
        "verified": True,    # deterministic Postgres data — no hallucination risk
        "warning":  None,
    }
    return {"agent_results": [result]}


@traceable(name="QueryDispatcher·Hasura", run_type="tool")
def _log_hasura(query_type: str, variables: dict, row_count: int, answer_preview: str) -> dict:
    """LangSmith span — records what was sent to Hasura and what came back."""
    return {
        "query_type":     query_type,
        "variables_sent": variables,
        "rows_returned":  row_count,
        "answer_preview": answer_preview[:300],
    }


async def _execute(query_type: str, params: dict, customer_id: str, customer_360: dict) -> str:
    """Execute the named Hasura template and format the result."""
    date_from    = params.get("date_from", "")
    date_to      = params.get("date_to", "")
    date_from_ts = _to_ts(date_from)
    date_to_ts   = _to_ts(date_to)

    def _log(variables: dict, data: dict, answer: str) -> str:
        """Call LangSmith span inline; return answer unchanged."""
        rows = sum(len(v) if isinstance(v, list) else 1 for v in data.values())
        _log_hasura(query_type, variables, rows, answer)
        return answer

    try:
        if query_type == "profile_demographics":
            v = {"cid": customer_id}
            data = await hasura_client.query(_Q_PROFILE, v)
            return _log(v, data, _fmt_profile(data))

        if query_type == "product_portfolio_summary":
            v = {"cid": customer_id}
            data = await hasura_client.query(_Q_PORTFOLIO, v)
            return _log(v, data, _fmt_portfolio(data))

        if query_type == "aggregate_by_category":
            v = {"cid": customer_id, "from": date_from_ts, "to": date_to_ts}
            data = await hasura_client.query(_Q_AGG_CATEGORY, v)
            return _log(v, data, _fmt_agg_category(data, date_from, date_to))

        if query_type == "aggregate_by_merchant":
            merchant_name = params.get("merchant_name", "").strip()
            merchant_cat  = params.get("merchant_category", "").strip()

            if merchant_name:
                v = {"cid": customer_id, "from": date_from_ts, "to": date_to_ts,
                     "name": f"%{merchant_name}%"}
                data = await hasura_client.query(_Q_AGG_MERCHANT_BY_NAME, v)
                return _log(v, data, _fmt_agg_merchant_by_name(data, merchant_name, date_from_ts, date_to_ts))
            else:
                v = {"cid": customer_id, "from": date_from_ts, "to": date_to_ts, "cat": merchant_cat}
                data = await hasura_client.query(_Q_AGG_MERCHANT_BY_CAT, v)
                return _log(v, data, _fmt_agg_merchant_by_cat(data, date_from_ts, date_to_ts))

        if query_type == "transaction_count_by_period":
            v = {"cid": customer_id, "from": date_from_ts, "to": date_to_ts}
            data = await hasura_client.query(_Q_TXN_COUNT, v)
            return _log(v, data, _fmt_txn_count(data, date_from, date_to))

        if query_type == "casa_balance_summary":
            v = {"cid": customer_id}
            data = await hasura_client.query(_Q_CASA, v)
            return _log(v, data, _fmt_casa(data))

        if query_type == "loan_balance_remaining":
            v = {"cid": customer_id}
            data = await hasura_client.query(_Q_LOAN, v)
            return _log(v, data, _fmt_loan(data))

        if query_type == "term_deposit_list":
            v = {"cid": customer_id}
            data = await hasura_client.query(_Q_TERM_DEPOSIT, v)
            return _log(v, data, _fmt_term_deposit(data))

        if query_type == "insurance_contract_status":
            v = {"cid": customer_id}
            data = await hasura_client.query(_Q_INSURANCE, v)
            return _log(v, data, _fmt_insurance(data))

        if query_type == "segment_gap_analysis":
            return _fmt_segment_gap(customer_360)

    except Exception as e:
        return f"Không thể truy vấn dữ liệu ({query_type}): {e}"

    return f"Loại truy vấn '{query_type}' chưa được hỗ trợ."
