# Project Development & Technical Evaluation Report

## 1. Executive Summary

This report documents the architectural decisions, development methodology, problems encountered, and future roadmap for the **Mini AI Business Intelligence Assistant** — a placement project that lets non-technical users query sales transaction data in plain English and receive verifiable answers backed by audited SQL.

---

## 2. Which AI Tools Were Used

[DEV_TOOLS_USED]

**Runtime AI tooling:**
- **`google-genai` SDK** — the official Google Gen AI Python SDK, used at runtime to call `gemini-3.6-flash` (configured via `LLM_MODEL` in `.env`). This model is the current stable Flash generation as documented at [ai.google.dev](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash).
- **`sqlparse`** — token-level SQL parser used as a guardrail to validate every SQL statement before execution.

---

## 3. How AI Was Used During Development

### A. Data Exploration & Anomaly Profiling
AI was used to inspect the raw 51-row CSV and rapidly identify data quality issues before authoring the schema:
- Missing `Unit_price` in `TXN0051`
- Returned order `TXN0033` inflating gross revenue
- Zero-quantity order `TXN0034`
- European date format (`DD-MM-YYYY`) requiring ISO normalisation

### B. Architecture & ReAct Loop Design
AI assisted in structuring the **ReAct (Reasoning + Acting)** pattern:
- **Thought**: parse intent and apply guards
- **Action**: route to deterministic engine or LLM
- **Observation**: validate and execute SQL
- **Synthesis**: format result for the user

The keyword router handles the 5 benchmark questions and ~7 exploratory categories with deterministic SQL. Unknown questions go to `gemini-3.6-flash` for text-to-SQL generation, with a retry loop that feeds validation errors back to the model.

### C. Test Authoring
AI generated 59 automated test cases across 6 suites covering ETL, SQL validation, analytics benchmarks, agent guardrails, REST endpoints, and LLM-path mocking.

### D. Relationship to Agentic Frameworks
This ReAct loop implements the same concepts as **LangChain/LangGraph** (tool-calling agent with observation + memory) and **Google ADK** (agent with guardrails and tool dispatch), but as plain Python to keep it transparent and interviewable.

**Why RAG is not needed**: the data is structured (tabular sales records). SQL retrieval on `v_completed_sales` is exact — there is nothing to embed or approximate. RAG is better suited for unstructured document corpora. Vectorless, schema-grounded SQL retrieval is the correct choice here.

---

## 4. Problems Encountered & How They Were Debugged

### Problem 1: Revenue Corruption — Missing Unit Price (TXN0051)
- **Issue**: `TXN0051` had an empty `Unit_price`. Standard `SUM()` would silently undercount revenue by $6,000.
- **Diagnosis**: pandas profiling found 1 null in `Unit_price`; comparing with other Laptop Stand orders confirmed $1,200.00 as the correct price.
- **Resolution**: ETL imputation pipeline with catalog price map; `is_imputed=1` flag; `data_quality_audit` log entry.

### Problem 2: Inflated Revenue from Returned Orders (TXN0033)
- **Issue**: Returned Monitor order ($19,000) inflated gross revenue figures.
- **Resolution**: `v_completed_sales` view filters `WHERE status = 'Completed'`; all revenue calculations use this view exclusively.

### Problem 3: Date Sorting in SQLite
- **Issue**: European `DD-MM-YYYY` strings sort incorrectly alphabetically.
- **Resolution**: ETL converts to ISO `YYYY-MM-DD`; pre-computed `year_month` column (`YYYY-MM`) added for GROUP BY.

### Problem 4: No LLM at Runtime (found during upgrade)
- **Issue**: The original `config.py` had `GEMINI_API_KEY` and `OPENAI_API_KEY` — neither was wired to any real API call. The LLM was not actually invoked.
- **Diagnosis**: Code audit showed `llm_client.py` did not exist; the agent was purely deterministic.
- **Resolution**: Wrote `src/llm_client.py` using the `google-genai` SDK. The LLM now runs for unknown question types when a key is present.

### Problem 5: SQL Validator Bypass (found during upgrade)
- **Issue**: The original `database.execute_query()` called the DB directly without validation. Deterministic benchmark queries bypassed `SQLValidator`.
- **Diagnosis**: `git grep validate_and_sanitize` showed it was only called inside `agent.py` for the LLM path — not for the 5 engine methods.
- **Resolution**: Added `SQLValidator.validate_and_sanitize()` as a choke point inside `DatabaseManager.execute_query()`. All SQL now passes through it regardless of source.

### Problem 6: `.env` Not Ignored (found during upgrade)
- **Issue**: `.gitignore` did not list `.env`, so a real API key could be committed.
- **Resolution**: Added `.env`, `.env.*`, `!.env.example`, `.venv/` entries to `.gitignore`.

### Problem 7: Retired Model Name in Docs
- **Issue**: Documentation and config referenced `gemini-2.0-flash`, which is shut down.
- **Diagnosis**: Checked [ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash); stable model is `gemini-3.6-flash`.
- **Resolution**: Updated `LLM_MODEL` default in `config.py` and all documentation.

### Problem 8: Documentation Inaccuracies
- **Issues**: README claimed "AST-based parsing", "autonomous", "zero hallucination", "SOC2/HIPAA/ISO", and a full AWS deployment blueprint with a `deploy.yml` that does not exist.
- **Resolution**: Rewrote README to describe the real system; shrunk `cloud_deployment_aws.md` to a future-work note; removed all unimplemented claims.

---

## 5. What Would Be Improved With Another Day of Work

1. **Real multi-model LLM routing**: use the Gemini `function_calling` feature to let the model choose between the 5 deterministic tools and free SQL — cleaner than the keyword router.
2. **Multi-turn memory**: stateful session with conversation history so follow-up questions like "Which region was second?" work correctly.
3. **Streaming responses (SSE)**: stream the agent's ReAct trace in real time.
4. **Larger dataset & more question types**: extend the router or replace it with embedding-based intent matching for broader coverage.
5. **Cloud deployment**: containerise with Docker; deploy to AWS Lambda + Aurora Serverless + Bedrock (see `docs/cloud_deployment_aws.md` for the outline).
