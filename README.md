# ⚡ Mini AI Business Intelligence Assistant

A placement-project Business Intelligence assistant: ask a question in plain English, get an answer backed by verified SQL, with interactive charts and a full reasoning trace.

---

## 🌟 How It Works

The assistant uses a **keyword router + Gemini LLM** approach:

- **Known question types** (total revenue, top product, monthly trend, top region, month-to-month change, category, channel, discount, returns, data quality) route directly to **verified deterministic SQL** — the answer is always exact.
- **Unknown question types** go to the **Gemini LLM** (`gemini-3.6-flash` via `LLM_MODEL` in `.env`), which generates a SQL query. That SQL is validated by a token-level `sqlparse` choke point before any execution — destructive statements are blocked regardless of source.
- If the LLM is unavailable or the question is outside sales data, a clear "I can't answer that" is returned.

### Security layers (in order)
1. `max_length=500` on the question → HTTP 422 if exceeded
2. Regex attack-pattern guard on the question *text* (blocks `DROP TABLE`, `DELETE FROM`, etc. in the question itself)
3. Keyword out-of-domain guard for obvious non-sales questions
4. LLM `OUT_OF_SCOPE` sentinel → `status: out_of_domain`
5. `SQLValidator.validate_and_sanitize` in `database.execute_query` — **every** SQL statement passes through this, regardless of origin
6. SQLite `PRAGMA query_only = ON` engine lock

---

## 📊 Benchmark Questions & Exact Answers

| # | Question | Answer |
|---|---|---|
| Q1 | What is the total revenue? | **$1,445,200.00** net (50 completed orders) |
| Q2 | Which product generated the highest revenue? | **Monitor** — $473,000.00 |
| Q3 | What is the monthly revenue trend? | Jan $210,250 → peak May $318,500 → Jun $217,250 |
| Q4 | Which region generated the highest sales? | **South** — $411,200.00 |
| Q5 | How did revenue change between January and February? | **+$24,350.00 (+11.58%)** |

---

## 🏗️ Project Structure

```
mini_bi_assistant/
├── data/
│   ├── raw/sales_data.csv          # Raw 51 sales transaction records
│   ├── processed/sales.db          # Cleaned SQLite database with indexes & views
│   └── data_dictionary.md
│
├── src/
│   ├── config.py                   # Paths, catalog prices, LLM settings (loads .env)
│   ├── database.py                 # SQLite manager — validate_and_sanitize choke point here
│   ├── sql_validator.py            # Token-level validation via sqlparse
│   ├── etl.py                      # Ingestion, cleaning, imputation, audit logging
│   ├── analytical_engine.py        # Deterministic queries & keyword intent router
│   ├── llm_client.py               # google-genai SDK wrapper (gemini-3.6-flash)
│   ├── agent.py                    # ReAct loop: guards → router → LLM → deterministic
│   └── api.py                      # FastAPI REST app & static file server
│
├── static/                         # Web UI (HTML/CSS/JS + Chart.js)
├── tests/                          # 59 automated tests
├── docs/                           # Architecture & future cloud notes
├── .env.example                    # Copy this to .env and add your API key
├── requirements.txt
├── run.py
├── REPORT.md
└── README.md
```

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.10+ (tested on 3.13)

### 2. Installation
```bash
git clone <repo-url>
cd AI_BI_Assistant

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Set up your API key (optional — app works without one)
```bash
copy .env.example .env        # Windows
# or: cp .env.example .env   # Linux/macOS
```

Open `.env` and set:
```
GOOGLE_API_KEY=your-key-here
```

> ⚠️ **Never commit `.env`** — it is already in `.gitignore`.  
> Without a key, the assistant runs in deterministic-only mode and answers all known question types correctly. Only truly ad-hoc/unknown questions need the LLM.

### 4. Launch
```bash
python run.py
```
- Web Dashboard: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Swagger API Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 🧪 Running Tests

```bash
python -m pytest -q
```

59 tests — ETL, SQL validation, analytics benchmarks, agent logic, REST API, LLM guardrails.

---

## 🗄️ How Data Is Stored and Queried

1. **ETL** (`src/etl.py`): reads `sales_data.csv` (51 rows), normalises dates from `DD-MM-YYYY` to `ISO 8601`, imputes 1 missing unit price from catalog, flags zero-quantity and returned orders, logs all decisions to `data_quality_audit`.
2. **SQLite database** (`data/processed/sales.db`):
   - `sales_transactions` — raw and cleaned data with `is_imputed` flag
   - `v_completed_sales` — view filtering `WHERE status = 'Completed'`; used for **all** revenue calculations
   - `data_quality_audit` — one row per anomaly detected during ETL
   - Indexes on `product`, `region`, `year_month` for fast GROUP BY queries
3. **Query execution**: every SQL statement — whether from the deterministic engine, the LLM, or an exploratory branch — goes through `database.execute_query()`, which calls `SQLValidator.validate_and_sanitize()` before touching SQLite. The connection also has `PRAGMA query_only = ON`.

---

## 🛡️ Data Quality & Anomaly Handling

| Issue | Record | Action |
|---|---|---|
| Missing unit price | TXN0051 — Laptop Stand | Imputed $1,200 from catalog; `is_imputed=1` |
| Zero quantity | TXN0034 — Keyboard | Flagged `ZERO_QUANTITY`; $0 revenue |
| Returned order | TXN0033 — Monitor 2 units | Flagged `RETURNED_ORDER`; excluded from `v_completed_sales` |

Audit trail available at `GET /api/data-quality`.

---

## ⚠️ Known Limitations

- **Small dataset**: 51 rows, 50 completed orders. Results are exact for this dataset but not statistically significant.
- **Completed orders only**: only `status = 'Completed'` rows count as revenue. Returned and zero-quantity records are excluded.
- **Known question types only (without key)**: without a Gemini API key the assistant only answers the named question categories listed above. Truly ad-hoc questions return "I can't answer that."
- **LLM SQL not guaranteed**: the LLM generates SQL that satisfies the rules most of the time, but its output is validated and all rows are always shown alongside the answer so you can verify it.
- **No multi-turn memory**: each question is answered independently; there is no session context.
- **Keyword router coverage**: the intent router recognises the 5 benchmark questions and ~7 exploratory categories by keyword. New question types require either a Gemini key or extending the router.
