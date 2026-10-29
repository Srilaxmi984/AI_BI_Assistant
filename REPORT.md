# Project Development & Technical Evaluation Report

## 1. Executive Summary
This report documents the architectural decisions, development methodology, problem-solving journey, and future roadmap for the **Mini AI Business Intelligence Assistant**. The application was built to enable non-technical business users to query transaction data in natural language and receive verifiable, deterministic answers backed by actual database queries.

---

## 2. Which AI Tools Were Used
During development, the following AI tools and models were utilized:
1. **Antigravity Agentic Assistant (powered by Google Gemini 3.8)**:
   - Used for interactive pair-programming, automated code generation, test case authoring, and exploratory data analysis.
   - Operated with direct filesystem and shell command execution capabilities to automate testing and iteration cycles.
2. **LLM Foundation Models (Amazon Bedrock / Claude 3.5 Sonnet & OpenAI GPT-4o Reference Architectures)**:
   - Used to formulate prompt designs for text-to-SQL generation, zero-shot schema understanding, and executive business narrative synthesis.
3. **AST-based SQL Grammar Parsers (`sqlparse`)**:
   - Deployed as an AI guardrail and syntactic verification filter to validate SQL tokens before execution.

---

## 3. How AI Was Used During Development

### A. Accelerated Data Exploration & Anomaly Profiling
AI was used to inspect the raw 51-row transaction CSV file to rapidly identify statistical distributions, missing values, and anomalies before authoring the database schema. AI scripts detected:
- The missing `Unit_price` in record `TXN0051`.
- The single returned order `TXN0033`.
- The zero-quantity record `TXN0034`.
- The `DD-MM-YYYY` date formats that required normalization into ISO `YYYY-MM-DD`.

### B. Architecture & ReAct Loop Implementation
AI assisted in structuring the core **ReAct (Reasoning + Acting) Agent Pattern**:
- **Thought**: The agent parses the user's natural language input, performs entity extraction (e.g. matching month names like "January" and "February" to `2026-01` and `2026-02`), and evaluates domain boundaries.
- **Action**: The agent either selects a deterministic query tool or synthesizes a targeted SQL query.
- **Observation**: The query is validated and executed against SQLite with read-only pragma locks.
- **Synthesis**: The agent translates the query result into a natural language executive summary, calculates month-over-month variances, and provides supporting data tables and chart configs.

### C. Test Automation & Edge Case Generation
AI was leveraged to author 33 automated test cases across 5 test suites (`test_etl.py`, `test_sql_validator.py`, `test_analytics.py`, `test_agent.py`, `test_api.py`), ensuring complete coverage of security constraints, arithmetic correctness, exploratory business questions, and REST endpoints.

---

## 4. Problems Encountered & How They Were Debugged

### Problem 1: Silent Revenue Corruption via Missing Unit Price (`TXN0051`)
- **Issue**: Transaction `TXN0051` had an empty `Unit_price` field. If loaded as `NULL`, standard SQL aggregations like `SUM(quantity * unit_price)` would either drop the record or yield incorrect results ($1,439,200 instead of $1,445,200).
- **Diagnosis**: Running exploratory pandas profiling revealed that `Unit_price` had 1 null value, but all other `Laptop Stand` orders consistently had a unit price of $1,200.00.
- **Resolution**: Implemented an automated imputation policy during ETL. The pipeline maintains a master product catalog price map, imputes missing prices with $1,200.00, sets `is_imputed = 1`, and logs a record to `data_quality_audit` for full governance.

### Problem 2: Misleading Revenue from Returned Orders (`TXN0033`)
- **Issue**: Transaction `TXN0033` (Monitor, Quantity 2, Price $9,500 = $19,000) was marked as `Status = 'Returned'`. If included in gross revenue, it inflates commercial performance with uncollected income.
- **Diagnosis**: Grouping revenue by status showed 50 completed orders and 1 returned order.
- **Resolution**: Created a dedicated analytical database view `v_completed_sales` that filters `WHERE status = 'Completed'`, ensuring that all executive metrics represent realized sales. Simultaneously, the raw `sales_transactions` table preserves the returned record for auditing.

### Problem 3: Date Arithmetic & Month Ordering in SQLite
- **Issue**: The input dates were formatted as strings in European format (`DD-MM-YYYY`, e.g. `03-01-2026`). In SQLite, alphabetical sorting on `DD-MM-YYYY` results in chronological sorting errors (e.g. `01-03-2026` sorting before `02-02-2026`).
- **Diagnosis**: Running `ORDER BY order_date` resulted in incorrect monthly trends.
- **Resolution**: Normalised the dates during ETL into standard ISO-8601 `YYYY-MM-DD` and added a pre-computed `year_month` column (`YYYY-MM`) with index. This enabled clean SQL aggregations (`GROUP BY year_month ORDER BY year_month ASC`).

### Problem 4: SQL Injection & Destructive Query Protection
- **Issue**: Pure LLM text-to-SQL is susceptible to prompt injection, hallucinated tables, or destructive commands (`DROP TABLE`, `UPDATE`, `DELETE`).
- **Diagnosis**: Testing stacked queries (`SELECT ...; DROP TABLE ...`) showed naive regex checks could be bypassed.
- **Resolution**: Implemented a defense-in-depth security layer:
  1. AST parsing via `sqlparse` verifying single `SELECT` statements.
  2. Keyword blacklist for destructive operations.
  3. Table whitelisting (`ALLOWED_TABLES`).
  4. SQLite engine-level lock: `PRAGMA query_only = ON;`.

---

## 5. What Would Be Improved With Another Day of Work

If allocated an additional day, the following enhancements would be prioritized:

1. **Enterprise Cloud Deployment on AWS**:
   - Containerize the application using Docker and deploy to **AWS Lambda** fronted by **Amazon API Gateway**.
   - Connect **Amazon Lex** as a conversational bot and voice channel.
   - Use **Amazon Bedrock (Claude 3.5 Sonnet)** with the Bedrock Converse API for zero-shot text-to-SQL on complex ad-hoc queries.
   - Store transaction data as partitioned Apache Parquet files in **Amazon S3** and query them via **Amazon Athena**.

2. **Vector Retrieval-Augmented Generation (RAG) for Business Metadata**:
   - Embed schema documentation, KPI definitions, and business glossaries into a vector store (e.g. pgvector or Amazon OpenSearch).
   - Enable the agent to answer definitional questions like *"How do we calculate net revenue vs gross revenue?"*.

3. **Multi-Turn Conversational Memory**:
   - Implement stateful session tracking with LangGraph checkpointers backed by Redis or Amazon DynamoDB.
   - Allow follow-up contextual questions like *"Which region was second?"* or *"Break that down by channel"*.

4. **Automated Anomaly Alerts & Push Notifications**:
   - Implement statistical trend detection (e.g., flagging the 31.8% drop in revenue between May and June 2026).
   - Integrate with AWS EventBridge and SNS to push real-time alerts to Slack or executive email.

5. **Streaming Responses (SSE / WebSockets)**:
   - Stream the agent's ReAct thoughts in real time as they occur to improve user perceived responsiveness.
