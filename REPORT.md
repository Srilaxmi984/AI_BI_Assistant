# Project Report

## 1. Summary

The Mini AI Business Intelligence Assistant answers sales questions in plain English. Known questions use verified SQL. Other questions go to Gemini, which writes one SELECT that is validated and run on a read-only database. The answer text is always built by Python from the returned rows, and the SQL, rows and reasoning trace are shown to the user.

What works: all five benchmark questions with exact figures, data cleaning with an audit log, a validated and read-only query path, a Gemini text-to-SQL path with retry and fallback, a REST API, a dashboard, and 59 automated tests.

What is limited: a 51-row dataset, a keyword router for known questions, no multi-turn memory, and token-level SQL validation. See "Known Limitations" in the README.

## 2. AI tools used

**During development**

- **Antigravity (powered by Google Gemini)** — primary pair-programming assistant used throughout the project. Used for planning, generating code (ETL, agent, LLM client, API, UI, test suites), iterative debugging, and all structured code review. All generated code was reviewed and run against the tests before being committed.
- **Google AI Studio** — used to test and iterate on the `gemini-3.6-flash` system prompt design (text-to-SQL rules, OUT_OF_SCOPE sentinel, schema context, retry behaviour).

**At runtime**

- Google Gemini through the `google-genai` SDK. The model name comes from the `LLM_MODEL` environment variable (default `gemini-3.6-flash`). It is used only to turn a question into one SELECT statement, and to answer `OUT_OF_SCOPE` for questions that are not about sales.
- The model never writes numbers in answers, and the app works without it.

## 3. How AI was used

- **Exploring the data**: profiling the CSV to find the missing price (TXN0051), the returned order (TXN0033), the zero-quantity order (TXN0034) and the `DD-MM-YYYY` date format.
- **Generating code**: the ETL, SQL validator, analytical engine, API and dashboard were drafted with an AI coding assistant, then run and corrected.
- **Writing tests**: the assistant proposed test cases for valid, invalid and edge inputs; the Gemini tests use a mocked client so they are repeatable and need no key.
- **Reviewing**: an audit of the first version found gaps between the documentation and the code, which drove the second round of changes (section 4).
- **Runtime**: Gemini turns unrecognised questions into SQL, with validation and a fallback around it.

Every AI-written piece was run against the tests and the five known answers before being kept.

## 4. Problems encountered and how they were debugged

| # | Problem | How it was found | Fix |
|---|---|---|---|
| 1 | Revenue would be wrong because of a missing unit price (TXN0051) | Profiling showed one null price, so a plain `SUM(quantity * unit_price)` was off by $6,000 | ETL imputes the catalog price ($1,200), sets `is_imputed = 1`, logs it to `data_quality_audit` |
| 2 | A returned order inflated revenue (TXN0033, $19,000) | Grouping by status showed 50 completed and 1 returned | The view `v_completed_sales` keeps completed orders only; the raw table keeps the record for audit |
| 3 | Months sorted wrongly | Dates were `DD-MM-YYYY` strings, so alphabetical order was not chronological | ETL converts to ISO dates and adds an indexed `year_month` column |
| 4 | SQL injection and destructive queries | A test with `SELECT ...; DROP TABLE ...` showed simple regex checks are easy to get around | Layered defence: one-SELECT check with `sqlparse`, keyword block, table whitelist, `LIMIT`, and `PRAGMA query_only` |
| 5 | **No LLM was actually called at runtime** | An audit of the code found no AI API call, only keyword routing, although the documentation described an AI agent | Added `llm_client.py` (Gemini), a text-to-SQL path with validation, one retry, fallback, and a `mode` field in every response |
| 6 | **The validator was bypassed** for the main queries | The audit showed it only ran in one branch of the agent | Moved validation into `database.py`'s query function so every query passes through one choke point; added tests that prove it |
| 7 | **Secrets were not protected** | `.env` was missing from `.gitignore` | Added `.env` rules, created `.env.example`, scanned git history for key patterns |
| 8 | **A retired model name** | Checking the Gemini docs showed `gemini-2.0-flash` was shut down on 1 June 2026, so calls would fail and silently fall back | Default model set to a current one and made configurable through `LLM_MODEL` |
| 9 | A malicious question like "DROP TABLE ..." received a normal-looking answer | Reading the agent paths | Attack-pattern guard rejects it with status `rejected`; the pattern list avoids plain words so "revenue update for May" still works |
| 10 | Documentation claimed things that did not exist (a deploy workflow, wrong test counts, "AST-based", "zero hallucination", compliance claims, tools not used) | Comparing every claim in the docs with the code | Rewrote the docs to describe only what is implemented |
| 11 | `pytest` failed with "No module named src" | Bare `pytest` does not add the project folder to the import path | Added `pytest.ini` with `pythonpath = .` |
| 12 | Model-written SQL gives results of any shape | Design review | A generic Python formatter builds the answer, table and chart type from the columns; money formatting depends on the column name |
| 13 | **`timeout` field rejected by `GenerateContentConfig`** | Running the agent directly showed a Pydantic validation error in `llm_client.py` | Removed `timeout` from `GenerateContentConfig`; the SDK handles transport-level timeouts automatically |

Debugging approach: reproduce with a failing test or a direct query, fix the cause, and add a test so it cannot return. The five benchmark figures were re-checked after every change.

## 5. How the design relates to agent frameworks and RAG

- The loop is a ReAct-style agent: guard, choose a tool (verified SQL or Gemini), run it, observe rows, write the answer. In LangGraph it would be a graph with a router node, a SQL tool node, a validator node and a retry edge. In Google ADK the engine and SQL runner would be tools of one agent. Dify could express the same flow as a workflow with an LLM node and a code node.
- The project does not use LangChain, LangGraph, ADK or Dify, to keep every step readable and explainable.
- **RAG is not needed here.** The data is structured and the answer comes from an exact SQL query, so there is nothing to embed. This is close to vectorless retrieval: retrieval by query over a table. Vector RAG would become useful if the assistant had to answer from text documents such as KPI definitions or a business glossary.

## 6. What I would improve with another day

1. **Evaluate the Gemini path properly**: build a set of 30 or more questions with expected SQL results and measure accuracy, rather than relying on spot checks.
2. **Multi-turn memory** so follow-ups like "break that down by region" work.
3. **A business glossary** (definitions of net revenue, AOV and so on) retrieved with embeddings, to answer definition questions and improve the SQL prompt.
4. **A larger dataset and a real database** to test performance and the validator on bigger schemas.
5. **A real SQL parser** (for example `sqlglot`) in place of token-level checks.
6. **Operations**: authentication, rate limiting, and persistent logs of questions, SQL and latency.
7. **Cloud deployment** (see `docs/cloud_deployment_aws.md`), which is not done.
