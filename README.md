# Mini AI Business Intelligence Assistant

A small application that lets a business user ask questions about sales data in plain English and get answers backed by real SQL queries. Every answer shows the SQL that ran, the rows it returned, and a step-by-step trace of how it was produced.

Built with Python, FastAPI, SQLite and Chart.js, for an AI-assisted development assessment.

---

## How questions are answered

The app uses two paths, and the response always says which one was used in its `mode` field.

| Path | When | `mode` |
|---|---|---|
| **Verified engine** | Known question types: total revenue, top product, monthly trend, top region, change between two months, plus a few exploratory ones (category, channel, discounts, returns, data quality, average order value, units) | `deterministic` |
| **Gemini text-to-SQL** | Business questions the router does not recognise | `llm` |
| **Refused** | Empty, too long, SQL-attack patterns, out of domain, or unanswerable | `none` |

How the Gemini path works:

1. The model receives the question, the schema and the allowed views, and writes **one SELECT**.
2. The SQL is validated (see Security below) and run on a read-only connection.
3. The answer text is built by **Python from the returned rows**. The model never writes the numbers.
4. If validation fails, the app retries once, feeding the error back to the model. If that also fails, or there is no API key, or the model errors, it falls back to the verified engine or says it cannot answer.

The app works without an API key: the verified engine handles all benchmark questions.

---

## Benchmark questions and answers

| # | Question | Answer |
|---|---|---|
| 1 | What is the total revenue? | **$1,445,200.00** net (gross $1,449,700.00, discounts $4,500.00, 50 completed orders) |
| 2 | Which product generated the highest revenue? | **Monitor**, $473,000.00 |
| 3 | What is the monthly revenue trend? | $210,250.00 in January 2026, peak $318,500.00 in May, $217,250.00 in June |
| 4 | Which region generated the highest sales? | **South**, $411,200.00 (about 28.5% of total) |
| 5 | How did revenue change between two months? | January to February 2026: **+$24,350.00 (+11.58%)** |

Revenue always means completed orders only (view `v_completed_sales`).

---

## Project structure

```
AI_BI_Assistant/
├── data/
│   ├── raw/sales_data.csv         # 51 supplied sales transactions
│   ├── processed/sales.db         # SQLite database, built by the ETL (git-ignored)
│   └── data_dictionary.md         # Column documentation
├── src/
│   ├── config.py                  # Paths, catalog prices, env settings
│   ├── database.py                # SQLite access; validates every query (single choke point)
│   ├── sql_validator.py           # Token-level SQL validation with sqlparse
│   ├── etl.py                     # CSV load, cleaning, imputation, audit log
│   ├── analytical_engine.py       # Intent router and verified SQL for known questions
│   ├── llm_client.py              # Gemini client (google-genai)
│   ├── agent.py                   # Guards, routing, LLM path, answer building
│   └── api.py                     # FastAPI app and static file server
├── static/                        # index.html, style.css, app.js (Chart.js UI)
├── tests/                         # pytest suite (LLM is always mocked)
├── docs/
│   ├── architecture.md            # Diagrams and design explanation
│   └── cloud_deployment_aws.md    # Future work note (not implemented)
├── .env.example                   # Settings template (no secrets)
├── pytest.ini
├── requirements.txt
├── run.py                         # One-command start
├── REPORT.md                      # AI tools used, problems, debugging, improvements
└── README.md
```

---

## Setup and run

Requires Python 3.10+ and git.

```bash
git clone https://github.com/Srilaxmi984/AI_BI_Assistant.git
cd AI_BI_Assistant

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### Optional: enable the Gemini path

```bash
# Windows PowerShell
Copy-Item .env.example .env
# macOS / Linux
cp .env.example .env
```

Open `.env` and set your key (get one at https://aistudio.google.com/apikey):

```
GOOGLE_API_KEY=your_key_here
LLM_MODEL=gemini-3.6-flash
LLM_ENABLED=true
```

- Never commit `.env`. It is listed in `.gitignore`; only `.env.example` is tracked.
- Set `LLM_ENABLED=false`, or leave the key empty, to use only the verified engine.
- Model names change over time. If the model call fails, check the current model list in the Gemini API docs and update `LLM_MODEL`.

### Start the app

```bash
python run.py
```

`run.py` builds the database from the CSV if it does not exist, then starts the server.

- Dashboard: http://127.0.0.1:8000
- API docs (Swagger): http://127.0.0.1:8000/docs

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/query` | Body: `{"question": "..."}` (1 to 500 characters, otherwise HTTP 422) |
| `GET /api/kpis` | Headline numbers for the dashboard cards |
| `GET /api/data-quality` | The data quality audit log |
| `GET /health` | Health check |

`/api/query` returns:

```json
{
  "question": "What is the total revenue?",
  "answer": "...",
  "sql_query": "SELECT ...",
  "supporting_figures": {},
  "table_data": [],
  "chart_type": "metric_card",
  "chart_config": null,
  "reasoning_trace": [{"step": "Thought", "detail": "..."}],
  "execution_time_ms": 4.2,
  "data_quality_note": "...",
  "status": "success",
  "mode": "deterministic"
}
```

`status` is one of `success`, `rejected`, `out_of_domain`, `invalid_request`, `error`. `mode` is `llm`, `deterministic` or `none`.

---

## Tests

```bash
python -m pytest -q
```

The suite has **59 tests** covering ETL, the SQL validator, the five benchmark answers, the agent and its guards, the REST API, and the LLM path.

- The LLM is **mocked** in every test, so no API key or network is needed.
- Valid questions: all five benchmark answers are asserted to the exact figure.
- Invalid and malicious input: empty question, a 501-character question (HTTP 422), `DROP TABLE` in the question text, stacked queries, destructive SQL returned by a mocked model.
- Edge cases: out-of-domain questions, model failure with fallback, no API key, "show me the revenue update for May" (the word "update" must not trigger a rejection), and a check that SQL from the model is validated before it runs.

---

## How data is stored and queried

1. `src/etl.py` loads `data/raw/sales_data.csv` (51 transactions).
2. Cleaning rules:
   - Dates in `DD-MM-YYYY` are converted to ISO `YYYY-MM-DD`, and a `year_month` column (`YYYY-MM`) is added and indexed so months sort correctly.
   - The one missing unit price (`TXN0051`, Laptop Stand) is filled from the product catalog price ($1,200) and flagged `is_imputed = 1`.
   - The zero-quantity order (`TXN0034`) is flagged `ZERO_QUANTITY` and contributes $0 revenue.
   - The returned order (`TXN0033`, Monitor, $19,000) is flagged `RETURNED_ORDER`.
   - Every fix is written to the `data_quality_audit` table with a timestamp.
3. Data is stored in SQLite (`data/processed/sales.db`):
   - `sales_transactions`: all records, including the returned one, for auditing.
   - `v_completed_sales`: a view of completed orders only. All revenue figures come from this view.
   - `data_quality_audit`: the cleaning log.
4. Every question query runs on a read-only connection (`PRAGMA query_only = ON`) after passing the validator.

---

## Security and guardrails

Checks run in this order for every question:

1. **Empty or whitespace question**: rejected.
2. **Length**: more than 500 characters is rejected (HTTP 422 at the API).
3. **Attack patterns in the question text**: phrases like `drop table`, `delete from`, `insert into`, `update ... set`, `truncate table`, `alter table`, or `;` followed by a SQL keyword are rejected with status `rejected`. Ordinary words such as "update" alone are fine.
4. **Out of domain**: non-sales questions are refused without running a query.
5. **SQL validation** (`sql_validator.py`, applied inside `database.py` so nothing bypasses it): token-level checks with `sqlparse`.
   - Exactly one statement, and it must be a `SELECT`.
   - Destructive and administrative keywords are blocked (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `REPLACE`, `ATTACH`, `DETACH`, `TRUNCATE`, `PRAGMA`, and similar).
   - Only these tables and views may be referenced: `sales_transactions`, `v_completed_sales`, `data_quality_audit`.
   - A `LIMIT 1000` is added when none is present.
6. **Read-only connection**: even if validation were bypassed, SQLite refuses writes.

Validation is token-level plus a whitelist; it is not a full SQL parser.

Preventing wrong answers: numbers in answers are computed or formatted by Python from the returned rows, revenue questions are pointed at `v_completed_sales`, and the SQL, rows and reasoning trace are always shown so a person can check the result.

---

## Known limitations

- The dataset is small (51 rows), so results demonstrate the design, not scale.
- Only completed orders count as revenue; the returned order is excluded.
- The keyword router recognises a limited set of question types; anything else depends on the Gemini path.
- SQL written by the model is not guaranteed to match what the user meant, which is why the SQL and rows are always displayed.
- There is no multi-turn memory: each question is answered on its own.
- Out-of-domain detection uses a keyword list plus the model's own refusal, so unusual off-topic questions can slip through to the model path.
- Validation is token-level (sqlparse), not a full parser.
- Not production-hardened: there is no authentication, rate limiting or persistent logging.

---

## More documentation

- [docs/architecture.md](docs/architecture.md): diagrams and design decisions
- [REPORT.md](REPORT.md): AI tools used, problems found, debugging, and improvements
- [docs/cloud_deployment_aws.md](docs/cloud_deployment_aws.md): future work note
