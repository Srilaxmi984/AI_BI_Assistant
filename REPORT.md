# Project Report

## 1. Summary

The Mini AI Business Intelligence Assistant answers sales questions in plain English. Known questions use verified SQL. Other questions go to Gemini, which writes one SELECT that is validated and run on a read-only database. The answer text is always built by Python from the returned rows, and the SQL, rows and reasoning trace are shown to the user.

What works: all five benchmark questions with exact figures, data cleaning with an audit log, a validated and read-only query path, a Gemini text-to-SQL path with retry and fallback, a REST API, a dashboard, and 92 automated tests.

What is limited: a 51-row dataset, a keyword router for known questions, no multi-turn memory, token-level SQL validation, and a Gemini path that depends on an API key with access (otherwise the app falls back to verified SQL or says it cannot answer). See "Known limitations" in the README.

## 2. AI tools used

**During development**

- **Antigravity** (agentic code editor): generated and edited the first version of the project, then applied the upgrade in phases (secrets handling, the Gemini client, the validator choke point, the UI and the documents). The model used was whichever one was selected in Antigravity's model menu at the time.
- **Claude** (claude.ai chat): reviewed the code and the documents against the assessment brief, found where the documentation did not match the code, planned the fixes, and wrote parts of the final code: the filtered and ranked question engine (`breakdown.py`), the Gemini client and its reply cleaning (`llm_client.py`), the agent's failure messages, the test isolation (`conftest.py`), several test files, and the README and report text.
- **Google AI Studio**: used only to create the Gemini API key for the runtime path.

**At runtime**

- Google Gemini through the `google-genai` SDK. The model name comes from the `LLM_MODEL` environment variable (default `gemini-3.6-flash`). It is used only to turn a question into one SELECT statement, and to answer `OUT_OF_SCOPE` for questions that are not about sales.
- The model never writes numbers in answers, and the app works without it.

## 3. How AI was used

- **Exploring the data**: profiling the CSV to find the missing price (TXN0051), the returned order (TXN0033), the zero-quantity order (TXN0034) and the `DD-MM-YYYY` date format.
- **Generating code**: the ETL, SQL validator, analytical engine, API and dashboard were drafted with an AI coding assistant, then run and corrected.
- **Writing tests**: the assistants proposed test cases for valid, invalid and edge inputs; the Gemini tests use a mocked client, and `conftest.py` blocks the real API in every test, so the suite is repeatable, fast and needs no key.
- **Reviewing**: an audit of the first version found gaps between the documentation and the code, which drove the second round of changes (section 4).
- **Runtime**: Gemini turns unrecognised questions into SQL, with validation and a fallback around it.

Every AI-written piece was run against the tests and the five known answers before being kept, and the headline figures were recomputed separately from the raw CSV with a short script to confirm them.

## 4. Problems encountered and how they were debugged

| # | Problem | How it was found | Fix |
|---|---|---|---|
| 1 | Revenue would be wrong because of a missing unit price (TXN0051) | Profiling showed one null price, so a plain `SUM(quantity * unit_price)` was off by $6,000 | ETL imputes the catalog price ($1,200), flags the row `IMPUTED_UNIT_PRICE` in `data_quality_flag`, logs it to `data_quality_audit` |
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
| 12 | Questions with a filter were answered as if the filter was not there (for example "highest sales region in March" returned the all-time answer) | Reading how the router matched keywords | Added `breakdown.py`: filters and rankings are parsed into a small spec and run as verified SQL; tests check that regional figures for a month add up to that month's revenue |
| 13 | Ordinary words were read as months ("market" contains "mar", "may" is a common word, "1" is a digit) | Reviewing the month matching in `detect_intent` | Months are matched as whole words only, "may" only where it clearly means the month, and a month outside the data gets a "no sales data" answer |
| 14 | Numbers and names were typed into answer text (a "+32.3%" growth month and a fixed list of region names) | Reading the answer strings in `analytical_engine.py` | Those parts are now computed from the returned rows |
| 15 | Model-written SQL gives results of any shape | Design review | A generic Python formatter builds the answer, table and chart type from the columns; percentages are formatted before money so a column like `discounted_orders_pct` shows as 8.00% |
| 16 | Gemini's reply was explanation text, not SQL (the SQL sat inside a code block followed by commentary) | Calling the client directly showed prose instead of a query | `extract_sql()` takes one statement out of the reply and passes anything else on unchanged so the validator rejects it; the prompt now says to output only the statement; tests cover fenced, plain and stacked replies |
| 17 | The first live call failed with `403 PERMISSION_DENIED` ("free tier is not available for this project") | Running the client from the terminal and reading the last lines of the error | The key came from a Google project without Gemini API access; a key from a project with access fixed it. Meanwhile the fallback worked as designed, and the trace now explains the failure in plain words without repeating the raw error |
| 18 | A later call failed with `504 DEADLINE_EXCEEDED` | The same direct call | The 15 second timeout was too short for the model's thinking time; raised to 30 seconds, and the output-token limit was raised so the answer is not cut short |
| 19 | Tests that sent an unrecognised question called the real Gemini when a key was in `.env`, so three tests failed unpredictably and a run took over a minute | Comparing two pytest runs that gave different failures | `tests/conftest.py` makes the Gemini client fail instantly in every test; tests that need a model reply mock it explicitly |
| 20 | Some questions got a different figure than the one asked for (a percentage question returned plain revenue; "highest average order value" returned total revenue; "average discount" returned total discounts) | A list of questions with answers computed independently from the CSV | Percentages and shares go to Gemini; average order value and discounts per group are answered by verified SQL; with Gemini down these questions say they cannot be answered |
| 21 | The Gemini prompt listed a column that does not exist in the database | Printing the real columns of `v_completed_sales` | The schema in the prompt now matches the view, including the `data_quality_flag` values |

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