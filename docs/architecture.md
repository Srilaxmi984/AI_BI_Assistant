# Architecture

## Component Overview

```
User Browser
     │
     ▼
FastAPI (api.py)
  ├── POST /api/query  ──► SalesBIAgent.process_question()
  ├── GET  /api/kpis   ──► AnalyticalEngine (direct)
  └── GET  /api/*      ──► DatabaseManager (direct)
```

## Guard Order in process_question()

```
1. max_length > 500 → HTTP 422 (enforced in api.py via Pydantic max_length;
                                  also checked in agent for non-HTTP callers)
2. _SQL_ATTACK_PATTERNS match → status: rejected, mode: none
3. Known-irrelevant keyword AND intent==unknown → status: out_of_domain, mode: none
4. intent != "unknown" → go to step 7 (deterministic engine)
5. intent == "unknown" → try LLM:
     a. LLM returns "OUT_OF_SCOPE"  → status: out_of_domain, mode: none
     b. LLM returns SQL → validate → execute → status: success, mode: llm
     c. Retry once, feeding validation error back to LLM
     d. All retries fail → continue to step 6
6. No named exploratory keyword → status: out_of_domain, mode: none
                                    "I can't answer that question…"
7. Deterministic engine / named exploratory SQL → status: success, mode: deterministic
```

## SQL Validation Choke Point

`DatabaseManager.execute_query()` calls `SQLValidator.validate_and_sanitize()` on **every** SQL string before it reaches SQLite, regardless of whether the SQL came from the deterministic engine, the LLM, or an exploratory branch.

```
SQLValidator (sqlparse token-level)
  ├── Single SELECT statement only
  ├── Dangerous keyword blacklist (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, …)
  ├── Table whitelist (v_completed_sales, sales_transactions, data_quality_audit)
  └── Pass → SQLite with PRAGMA query_only = ON
```

## Sequence: Known Question Type

```
User → "What is the total revenue?"
  → api.py POST /api/query
  → agent: intent = "total_revenue"
  → AnalyticalEngine.get_total_revenue()
     → DatabaseManager.execute_query(sql)
        → SQLValidator: PASS
        → SQLite (query_only=ON)
  → "$1,445,200.00", mode: deterministic
```

## Sequence: Unknown Question Type (LLM active)

```
User → "Which customers bought in Q1?"
  → api.py POST /api/query
  → agent: intent = "unknown"
  → LLMClient.generate_sql(question)
     → gemini-3.6-flash (google-genai SDK, _SYSTEM_PROMPT)
     → Returns SQL (or "OUT_OF_SCOPE")
  → SQLValidator: validate
     ↳ FAIL? → retry with error appended, then fallback
     ↳ PASS  → DatabaseManager.execute_query(sanitized_sql)
                 → SQLite (query_only=ON)
  → mode: llm
```

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

## mode Field

Every `/api/query` response includes `mode`:
- `"deterministic"` — answered by a verified fixed SQL query
- `"llm"` — answered by Gemini-generated SQL (validated before execution)
- `"none"` — rejected, out_of_domain, or error
