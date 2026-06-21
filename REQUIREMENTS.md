# AI FrontLine Agent — User Requirements

## Users

**Sales Representatives** — bank staff who manage a portfolio of assigned customers and are responsible for sales, service, and relationship management.

---

## User Stories

### 1. Customer Lookup
- As a sales rep, I want to search for a customer by name, phone number, or email so I can quickly find who I'm about to call.
- As a sales rep, I want to see a list of my assigned customers so I know my portfolio at a glance.

### 2. Customer 360 View
- As a sales rep, I want to see a full profile of a customer — including their segment, KYC status, credit score, loyalty points, city, occupation, and income range — so I can understand who I'm dealing with before a call.
- As a sales rep, I want to see all of a customer's products (accounts, loans, credit cards, insurance) in one place so I don't have to switch between systems.
- As a sales rep, I want to see key metrics (total balance, total credit/debit, active loans, open cases) at a glance so I can quickly assess the customer's financial health.
- As a sales rep, I want to see a customer's recent transactions so I can understand their spending behavior.
- As a sales rep, I want to filter transactions by type (credit/debit) so I can focus on relevant activity.
- As a sales rep, I want to see all open and resolved support cases for a customer so I'm aware of any ongoing issues before reaching out.

### 3. AI Sales Assistant (Chat)
- As a sales rep, I want to ask the AI assistant questions about a customer in plain language so I can get answers without manually looking through data.
- As a sales rep, I want the AI to proactively highlight risks (overdue loans, open complaints) so I don't miss critical context during a call.
- As a sales rep, I want the AI to suggest which products to recommend for a specific customer, with a rationale, so I can make informed and relevant offers.
- As a sales rep, I want the AI to generate a tailored sales script or talking points for a product recommendation so I know how to start the conversation.
- As a sales rep, I want to see the AI's response as it streams in real time so I don't wait for long pauses.
- As a sales rep, I want to know when the AI is fetching data (e.g., "Loading customer profile…") so I understand what it's doing.
- As a sales rep, I want to clear the conversation and start fresh with a new customer so previous context doesn't bleed over.


### 4. Product Information
- As a sales rep, I want to look up the bank's credit card products — including fees, rewards, eligibility, and credit limits — so I can recommend the right card for a customer.
- As a sales rep, I want to compare cards by tier (Standard, Gold, Premium, Elite) so I can match the customer's profile to the right product.

### 5. Extended Customer Product Portfolio
- As a sales rep, I want to see a customer's full product portfolio — including bancassurance contracts, term deposits, loans, and lending facilities — not just credit cards, so I have a complete view of the relationship.
- As a sales rep, I want to see key details for each product type (e.g., contract status, maturity date, principal amount, premium, coverage type) so I can assess the customer's existing commitments before making a recommendation.

### 6. Contract-Aware AI Queries (Unstructured + Structured Data)
- As a sales rep, I want to ask the AI questions that require combining a customer's signed contracts (unstructured documents) with their structured profile data, so I can get answers that no single system can provide on its own.
  - *Example: "Has this customer signed a Life Insurance contract, and does that qualify them for the new VIP tier with $1,000 medical compensation while traveling?"*
- As a sales rep, I want the AI to extract relevant clauses or terms from a customer's contracts when answering eligibility or suitability questions, so I don't have to read through documents manually.
- As a sales rep, I want the AI to clearly indicate when its answer draws from a contract document versus structured profile data, so I can trust and verify the source of the information.

---

## Functional Requirements (not yet implemented)

### Opportunities
- As a sales rep, I want to see a list of sales opportunities for my portfolio so I can prioritize my outreach.
- As a sales rep, I want to track the status of each opportunity (open, won, lost) so I can manage my pipeline.

---

## Non-Functional Requirements

- **Speed:** The customer 360 view should load within 2 seconds of selecting a customer.
- **AI Query SLA (structured data only):** AI agent responses based purely on structured customer profile data should complete within 5 seconds.
- **AI Query SLA (unstructured or hybrid queries):** AI agent responses that require reading contract documents, or combining unstructured contracts with structured profile data, must either complete within 20 seconds OR begin streaming tokens to the UI immediately so the sales rep sees partial results progressively — they must never wait 20 seconds for the first visible output.
- **Availability:** The AI assistant should indicate clearly when it is unavailable and fall back gracefully.
- **Clarity:** All monetary amounts must be displayed in Vietnamese Dong (VND) with readable formatting (e.g., 500M VND, 1.2B VND).
- **Accuracy:** The AI must only answer based on real customer data fetched from the system — not guesses.
- **Source transparency:** When answering hybrid queries, the AI must cite whether each piece of information came from a structured record or a contract document.
- **Privacy:** A sales rep must only be able to view and act on customers assigned to them.
