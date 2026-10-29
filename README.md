# ⚡ Mini AI Business Intelligence Assistant

An autonomous AI Business Intelligence Assistant that enables business users to query enterprise sales data using natural language and receive executive-grade answers supported by deterministic database queries, interactive visualizations, and complete reasoning transparency.

---

## 🌟 Key Features

- **Autonomous ReAct Agent Loop**: Follows an explicit multi-step cycle (*Thought → Action → Observation → Synthesis*) for verifiable decision-making.
- **Deterministic Analytics Engine**: Zero hallucination risk — all answers and KPIs are calculated directly from verified database query results.
- **Zero-Trust SQL Security & Guardrails**:
  - AST-based parsing and token inspection with `sqlparse`.
  - Blocks all destructive statements (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, etc.).
  - Rejects multi-statement / stacked SQL injection attempts.
  - Whitelists permissible schema entities (`sales_transactions`, `v_completed_sales`, `data_quality_audit`).
  - **Database Engine Lock**: Automatically sets `PRAGMA query_only = ON` on all SQLite analytical connections.
- **Data Quality & ETL Pipeline**:
  - Automatically identifies missing unit prices (e.g. `TXN0051`) and imputes them via product catalog pricing.
  - Identifies and flags zero-quantity orders (e.g. `TXN0034`).
  - Distinguishes returned orders (e.g. `TXN0033`) from realized revenue.
  - Logs all anomalies with audit timestamps into a dedicated `data_quality_audit` table.
- **Interactive Modern UI & REST API**:
  - Executive KPI cards, Chart.js dynamic visual charts, quick-query chips, and structured tabular data views.
  - Full visibility into executed SQL and step-by-step agent reasoning traces.
- **Enterprise Cloud-Ready**:
  - Designed to easily deploy as a serverless service on AWS (AWS Lambda + Amazon Bedrock / SageMaker + Amazon Lex + Amazon S3).

---

## 📊 Benchmark Business Questions & Exact Answers

The assistant natively supports and resolves all 5 benchmark questions with exact figures:

| # | Question | Exact Answer | Executed SQL / Calculation |
| :--- | :--- | :--- | :--- |
| **Q1** | **What is the total revenue?** | **$1,445,200.00** Net Revenue (Gross: $1,449,700.00, Discounts: $4,500.00 across 50 completed orders). | `SELECT SUM(net_revenue) AS total_revenue FROM v_completed_sales;` |
| **Q2** | **Which product generated the highest revenue?** | **Monitor** generated **$473,000.00** net revenue (50 units sold). Followed by Desk ($222,500.00) and Office Chair ($210,600.00). | `SELECT product, SUM(net_revenue) as rev FROM v_completed_sales GROUP BY product ORDER BY rev DESC;` |
| **Q3** | **What is the monthly revenue trend?** | Revenue grew from **$210,250.00** (Jan 2026) to a peak of **$318,500.00** (May 2026, +32.3% MoM) before closing at **$217,250.00** (June 2026). | `SELECT year_month, SUM(net_revenue) FROM v_completed_sales GROUP BY year_month ORDER BY year_month ASC;` |
| **Q4** | **Which region generated the highest sales?** | **South** region generated **$411,200.00** (28.5% of total sales). Followed by North ($384,450.00), East ($352,700.00), and West ($296,850.00). | `SELECT region, SUM(net_revenue) FROM v_completed_sales GROUP BY region ORDER BY rev DESC;` |
| **Q5** | **How did revenue change between two months?** | Between January 2026 ($210,250.00) and February 2026 ($234,600.00), revenue **increased by +$24,350.00 (+11.58%)**. | `SELECT year_month, SUM(net_revenue) FROM v_completed_sales WHERE year_month IN ('2026-01', '2026-02') GROUP BY year_month;` |

---

## 🏗️ Project Architecture

```
mini_bi_assistant/
│
├── data/
│   ├── raw/sales_data.csv          # Raw 51 sales transaction records
│   ├── processed/sales.db          # Cleaned SQLite database with indexes & views
│   └── data_dictionary.md          # Comprehensive schema & column documentation
│
├── src/
│   ├── config.py                   # App configuration, catalog pricing & paths
│   ├── database.py                 # SQLite connection manager & query_only safety pragma
│   ├── sql_validator.py            # AST & regex safety validator (read-only, whitelist)
│   ├── etl.py                      # Data ingestion, cleaning, imputation & audit logging
│   ├── analytical_engine.py        # Deterministic analytics calculations & intent router
│   ├── agent.py                    # ReAct loop coordinator (Thought -> Action -> Observation)
│   └── api.py                      # FastAPI REST application & static file server
│
├── static/
│   ├── index.html                  # Responsive executive BI dashboard UI
│   ├── style.css                   # Modern dark-mode UI styling
│   └── app.js                      # Chart.js visualization, KPI loader & table renderer
│
├── tests/
│   ├── test_etl.py                 # Data loading, missing prices, returns, zero qty
│   ├── test_sql_validator.py       # Security checks (blocks DROP, DELETE, injection)
│   ├── test_analytics.py           # Verification of 5 benchmark analytical questions
│   ├── test_agent.py               # ReAct cycle, edge cases & guardrails
│   └── test_api.py                 # FastAPI endpoints (/health, /api/kpis, /api/query)
│
├── docs/
│   ├── architecture.md             # System architecture & Mermaid sequence diagrams
│   └── cloud_deployment_aws.md     # AWS Serverless & Agentic AI deployment blueprint
│
├── requirements.txt                # Pinned dependencies
├── run.py                          # 1-command startup script
├── REPORT.md                       # Comprehensive project report & AI usage retrospective
└── README.md                       # Documentation
```

---

## 🚀 Quickstart & Execution

### 1. Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- `git`

### 2. Installation
```bash
# Clone the repository
git clone <repo-url>
cd mini_bi_assistant

# Create and activate a virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Launch the Application (1-Command)
```bash
python run.py
```
This automatically runs the ETL pipeline (if not already built) and launches the server.

- **Web Dashboard**: Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.
- **Interactive Swagger API Docs**: Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

---

## 🧪 Running Automated Tests

Run the full automated test suite (33 test cases covering ETL, SQL validation, analytics, agent logic, and REST API):

```bash
pytest -v
```

Output:
```
tests/test_agent.py ................ PASSED
tests/test_analytics.py ............. PASSED
tests/test_api.py ................... PASSED
tests/test_etl.py ................... PASSED
tests/test_sql_validator.py ......... PASSED
======================== 33 passed in 3.81s ========================
```

---

## 🛡️ Data Quality & Anomaly Handling

During ingestion, the pipeline detected and handled 3 distinct data quality issues:
1. **Missing Unit Price (`TXN0051`)**: Order date 28-06-2026 had an empty unit price for `Laptop Stand`. The pipeline looked up the product's catalog price ($1,200.00), imputed the value, set `is_imputed = 1`, and logged the audit trail.
2. **Zero Quantity Order (`TXN0034`)**: Order for `Keyboard` had `Quantity = 0`. Net revenue calculated as $0.00 and flagged as `ZERO_QUANTITY`.
3. **Returned Order (`TXN0033`)**: Order for `Monitor` (2 units, $19,000) was marked as `Status = 'Returned'`. Flagged as `RETURNED_ORDER` and excluded from the realized revenue view `v_completed_sales`.

All actions are transparently auditable via `GET /api/data-quality`.
