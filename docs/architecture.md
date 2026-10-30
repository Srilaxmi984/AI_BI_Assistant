# Architecture

## System Overview

```mermaid
flowchart TD
    User([User Browser]) -->|"POST /api/query"| API["FastAPI\n(api.py)"]
    User -->|"GET /api/kpis"| API
    API --> Agent["SalesBIAgent\n(agent.py)"]

    subgraph Guards ["Guard Chain (in order)"]
        G1["1. max_length > 500 → HTTP 422"]
        G2["2. SQL attack-pattern regex → rejected"]
        G3["3. Irrelevant-keyword out-of-domain → out_of_domain"]
        G1 --> G2 --> G3
    end

    Agent --> Guards

    Guards --> Router{"Intent\nRouter"}

    Router -->|"known intent"| DET["Deterministic Engine\n(analytical_engine.py)\n5 benchmark methods"]
    Router -->|"unknown intent"| LLM_PATH["LLM Path\n(llm_client.py → gemini-3.6-flash)"]

    LLM_PATH -->|"OUT_OF_SCOPE"| OOD["out_of_domain, mode=none"]
    LLM_PATH -->|"SQL returned"| VAL

    DET --> DB

    subgraph Choke ["SQL Choke Point (database.py)"]
        VAL["SQLValidator.validate_and_sanitize\n(sqlparse token-level)"]
        DB["SQLite\n(PRAGMA query_only=ON)"]
        VAL -->|"PASS"| DB
        VAL -->|"FAIL → retry with error"| LLM_PATH
    end

    DB --> Response["Response\n{answer, mode, sql_query,\ntable_data, chart_config,\nreasoning_trace}"]

    subgraph Fallback ["LLM Unavailable fallback"]
        EXP["Named exploratory SQL\n(channel/category/discount/…)"]
        NOPE["'I can't answer'\nmode=none, status=out_of_domain"]
    end

    LLM_PATH -->|"no key / all retries fail"| Fallback
    EXP --> DB
```

---

## Guard Order in `process_question()`

| Step | Condition | Result |
|---|---|---|
| 1 | `len(question) > 500` | HTTP 422 (Pydantic `max_length`) |
| 2 | SQL attack pattern in text | `status: rejected, mode: none` |
| 3 | Irrelevant keyword AND `intent==unknown` | `status: out_of_domain, mode: none` |
| 4 | `intent != "unknown"` | → Deterministic engine (step 7) |
| 5a | LLM returns `OUT_OF_SCOPE` | `status: out_of_domain, mode: none` |
| 5b | LLM returns valid SQL | validate → execute → `mode: llm` |
| 5c | LLM retry | feed validation error back in user_prompt |
| 5d | All retries fail | → step 6 |
| 6 | Named exploratory keyword present | → exploratory SQL branch, `mode: deterministic` |
| 6 | No keyword, no LLM | `"I can't answer…"`, `mode: none` |
| 7 | Deterministic engine | verified fixed SQL, `mode: deterministic` |

---

## SQL Validation Choke Point

Every SQL statement — from the deterministic engine, the LLM, or an exploratory branch — passes through `DatabaseManager.execute_query()`, which calls `SQLValidator.validate_and_sanitize()` before touching SQLite.

```
SQLValidator (sqlparse token-level)
  ├── Single SELECT statement only
  ├── Dangerous keyword blacklist (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE…)
  ├── Table whitelist (v_completed_sales, sales_transactions, data_quality_audit)
  └── PASS → SQLite with PRAGMA query_only = ON
```

---

## Sequence: Known Question (e.g. "What is the total revenue?")

```mermaid
sequenceDiagram
    participant U as User
    participant A as api.py
    participant AG as agent.py
    participant AE as analytical_engine.py
    participant DB as database.py + SQLite

    U->>A: POST /api/query
    A->>AG: process_question()
    AG->>AG: Guards pass
    AG->>AE: detect_intent() → "total_revenue"
    AG->>AE: get_total_revenue()
    AE->>DB: execute_query(sql)
    DB->>DB: validate_and_sanitize() PASS
    DB-->>AE: rows
    AE-->>AG: result {answer, $1,445,200.00}
    AG-->>A: {mode: "deterministic", status: "success"}
    A-->>U: JSON response
```

---

## Sequence: Unknown Question (LLM path)

```mermaid
sequenceDiagram
    participant U as User
    participant AG as agent.py
    participant L as llm_client.py
    participant G as gemini-3.6-flash
    participant V as SQLValidator
    participant DB as SQLite

    U->>AG: "What is the revenue per customer segment?"
    AG->>AG: intent = "unknown", guards pass
    AG->>L: generate_sql(question, error_hint="")
    L->>G: generate_content(system_prompt + user_prompt)
    G-->>L: "SELECT segment, SUM(net_revenue)..."
    L-->>AG: sql string
    AG->>V: validate_and_sanitize(sql)
    alt PASS
        V-->>AG: (True, sanitized_sql, None)
        AG->>DB: execute_query(sanitized_sql)
        DB-->>AG: rows
        AG-->>U: {mode:"llm", status:"success"}
    else FAIL (attempt 1)
        V-->>AG: (False, "", error_msg)
        AG->>L: generate_sql(question, error_hint=error_msg)
        L->>G: retry with error appended
        G-->>L: corrected SQL
    end
```

---

## mode Field

Every `/api/query` response includes `mode`:

| Value | Meaning |
|---|---|
| `"deterministic"` | Answered by verified fixed SQL (benchmark or named exploratory) |
| `"llm"` | Answered by Gemini-generated SQL, validated before execution |
| `"none"` | Rejected, out_of_domain, invalid_request, or error — no SQL ran |

---

## File Map

| File | Responsibility |
|---|---|
| `src/config.py` | Paths, catalog prices, LLM settings; loads `.env` via `python-dotenv` |
| `src/database.py` | SQLite connection; **validator choke point** in `execute_query()` |
| `src/sql_validator.py` | Token-level `sqlparse` validation; `SQLValidationError` |
| `src/etl.py` | CSV → SQLite ETL; imputation; audit logging |
| `src/analytical_engine.py` | 5 deterministic benchmarks + keyword intent router |
| `src/llm_client.py` | `google-genai` wrapper; `OUT_OF_SCOPE` detection; fence stripping |
| `src/agent.py` | ReAct loop; all guards; LLM retry; mode field |
| `src/api.py` | FastAPI; `QueryResponse` with `mode`; 500-char limit |
| `static/` | Web UI: HTML, CSS, Chart.js |
| `tests/` | 59 automated tests across 6 suites |
