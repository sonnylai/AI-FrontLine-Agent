-- AI FrontLine Agent V2 — PostgreSQL Schema
-- Database: ai_frontline_v2
-- Run: psql -U admin -d ai_frontline_v2 -f scripts/schema.sql

-- ─────────────────────────────────────────────────────────────────────────────
-- Extensions
-- ─────────────────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- trigram search on names

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Sales Reps
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sales_reps (
    rep_id          VARCHAR(20)  PRIMARY KEY,       -- "REP-001"
    full_name       VARCHAR(100) NOT NULL,
    gender          CHAR(1)      CHECK (gender IN ('M', 'F')),
    email           VARCHAR(100) UNIQUE NOT NULL,
    phone           VARCHAR(20),
    branch          VARCHAR(100),
    active          BOOLEAN      DEFAULT TRUE,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Customers
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    customer_id         VARCHAR(20)  PRIMARY KEY,   -- "CUST-001"
    full_name           VARCHAR(100) NOT NULL,
    date_of_birth       DATE,
    gender              CHAR(1)      CHECK (gender IN ('M', 'F')),
    phone               VARCHAR(20),
    email               VARCHAR(100),
    national_id         VARCHAR(20)  UNIQUE,
    city                VARCHAR(100),
    occupation          VARCHAR(100),
    income_range        VARCHAR(50),
    segment             VARCHAR(20)  NOT NULL        -- Standard, Silver, Gold, Platinum, Elite
                        CHECK (segment IN ('Standard', 'Silver', 'Gold', 'Platinum', 'Elite')),
    kyc_status          VARCHAR(20)  DEFAULT 'Pending'
                        CHECK (kyc_status IN ('Verified', 'Pending', 'Rejected', 'Expired')),
    credit_score        SMALLINT     CHECK (credit_score BETWEEN 300 AND 850),
    loyalty_points      INTEGER      DEFAULT 0,
    relationship_since  DATE,
    assigned_rep_id     VARCHAR(20)  REFERENCES sales_reps(rep_id),
    created_at          TIMESTAMPTZ  DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_rep     ON customers(assigned_rep_id);
CREATE INDEX IF NOT EXISTS idx_customers_segment ON customers(segment);
CREATE INDEX IF NOT EXISTS idx_customers_name    ON customers USING GIN (full_name gin_trgm_ops);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Contracts
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contracts (
    contract_id     VARCHAR(30)  PRIMARY KEY,        -- "BAN-003-0009"
    customer_id     VARCHAR(20)  NOT NULL REFERENCES customers(customer_id),
    product_type    VARCHAR(30)  NOT NULL,
    product_id      VARCHAR(30),
    product_name    VARCHAR(150) NOT NULL,
    status          VARCHAR(20)  DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE', 'LAPSED', 'CLOSED', 'PENDING')),
    start_date      DATE,
    end_date        DATE,
    key_amount      BIGINT,                          -- premium / loan amount / balance
    key_rate        NUMERIC(6,4),                   -- interest rate if applicable
    extra_fields    JSONB        DEFAULT '{}',       -- product-specific fields
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contracts_customer     ON contracts(customer_id);
CREATE INDEX IF NOT EXISTS idx_contracts_product_type ON contracts(product_type);
CREATE INDEX IF NOT EXISTS idx_contracts_status       ON contracts(status);
CREATE INDEX IF NOT EXISTS idx_contracts_extra        ON contracts USING GIN (extra_fields);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Contract Clauses (structured — for insurance contracts)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contract_clauses (
    clause_id               VARCHAR(50)  PRIMARY KEY,
    contract_id             VARCHAR(30)  NOT NULL REFERENCES contracts(contract_id),
    clause_number           VARCHAR(20),             -- "7.3"
    title                   VARCHAR(200),
    conditions              TEXT,
    benefit                 TEXT,
    customer_qualifies      BOOLEAN,
    disqualification_reason TEXT,
    extra_fields            JSONB        DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_clauses_contract ON contract_clauses(contract_id);
CREATE INDEX IF NOT EXISTS idx_clauses_number   ON contract_clauses(clause_number);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Contract Coverages
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contract_coverages (
    coverage_id     VARCHAR(50)  PRIMARY KEY,
    contract_id     VARCHAR(30)  NOT NULL REFERENCES contracts(contract_id),
    coverage_type   VARCHAR(50),
    limit_amount    BIGINT,
    conditions      TEXT
);

CREATE INDEX IF NOT EXISTS idx_coverages_contract ON contract_coverages(contract_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Products Held  (summary of what products each customer holds)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products_held (
    id              SERIAL       PRIMARY KEY,
    customer_id     VARCHAR(20)  NOT NULL REFERENCES customers(customer_id),
    product_code    VARCHAR(30)  NOT NULL             -- "CASA", "CREDIT_GOLD", etc.
);

CREATE INDEX IF NOT EXISTS idx_products_held_customer ON products_held(customer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_held_unique ON products_held(customer_id, product_code);

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. Transactions
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id      VARCHAR(20)  PRIMARY KEY,    -- "TXN-000001"
    customer_id         VARCHAR(20)  NOT NULL REFERENCES customers(customer_id),
    account_id          VARCHAR(30),
    transaction_date    TIMESTAMPTZ  NOT NULL,
    amount              BIGINT       NOT NULL,        -- in VND
    type                VARCHAR(10)  CHECK (type IN ('DEBIT', 'CREDIT')),
    merchant_name       VARCHAR(150),
    merchant_category   VARCHAR(50),
    channel             VARCHAR(20),
    description         TEXT,
    status              VARCHAR(20)  DEFAULT 'COMPLETED',
    currency            CHAR(3)      DEFAULT 'VND'
);

CREATE INDEX IF NOT EXISTS idx_txn_customer ON transactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_txn_date     ON transactions(transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(merchant_category);
CREATE INDEX IF NOT EXISTS idx_txn_account  ON transactions(account_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Customer Long-Term Memory  (loaded by Orchestrator node ①)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customer_memory (
    id              SERIAL       PRIMARY KEY,
    customer_id     VARCHAR(20)  NOT NULL REFERENCES customers(customer_id),
    rep_id          VARCHAR(20)  REFERENCES sales_reps(rep_id),
    session_date    DATE         NOT NULL DEFAULT CURRENT_DATE,
    summary         TEXT,                            -- LLM-generated session summary
    key_concerns    TEXT[],                          -- extracted pain points / objections
    products_discussed VARCHAR(30)[],               -- product codes discussed
    follow_up_items TEXT[],                          -- action items for next call
    sentiment       VARCHAR(10)  CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    raw_metadata    JSONB        DEFAULT '{}',
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_customer ON customer_memory(customer_id);
CREATE INDEX IF NOT EXISTS idx_memory_date     ON customer_memory(session_date DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 9. Auto-update updated_at on customers
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_customers_updated_at ON customers;
CREATE TRIGGER trg_customers_updated_at
    BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
