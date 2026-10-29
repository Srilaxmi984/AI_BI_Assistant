# System Architecture

## 1. High-Level Architecture Overview
The Mini AI Business Intelligence Assistant is designed with a **layered, decoupled ReAct (Reasoning + Acting) architecture**. It bridges natural language queries from business stakeholders to deterministic database execution while enforcing zero-trust data safety and anti-hallucination guardrails.

```mermaid
flowchart TD
    User([Business Stakeholder]) -->|Natural Language Question| UI[Interactive BI Web Dashboard]
    UI -->|HTTP POST /api/query| API[FastAPI Application Backend]
    
    subgraph Agentic Reasoning Engine
        API --> Agent[SalesBIAgent - ReAct Coordinator]
        Agent -->|1. Thought: Intent & Guardrails| IntentRouter[Semantic Router & Domain Guardrail]
        IntentRouter -->|2. Action: Formulate SQL| SQLGen[Analytical Engine / SQL Synthesizer]
        SQLGen -->|3. Validate Query| Validator[SQLValidator - AST & Keyword Scanner]
    end

    subgraph Defense-in-Depth Database Layer
        Validator -->|Pass: Sanitized Read-Only Query| EngineLock[SQLite Engine Lock: PRAGMA query_only = ON]
        EngineLock --> DB[(SQLite Database: sales.db)]
        DB -->|4. Observation: Verified Rowset| Agent
    end

    subgraph Synthesis & Presentation
        Agent -->|5. Synthesis: Grounded Narrative| API
        API -->|Structured JSON Response| UI
        UI -->|Render| Cards[KPI Cards]
        UI -->|Render| Visuals[Chart.js Visualizations]
        UI -->|Render| Audit[Executed SQL & ReAct Trace]
    end
```

---

## 2. ReAct (Reasoning + Acting) Cycle

The assistant implements an explicit multi-step ReAct loop:

```mermaid
sequenceDiagram
    autonumber
    actor User as Business User
    participant UI as Web Dashboard
    participant API as FastAPI Backend
    participant Agent as SalesBIAgent
    participant Validator as SQLValidator
    participant DB as SQLite (Read-Only)

    User->>UI: Types: "What is the monthly revenue trend?"
    UI->>API: POST /api/query {"question": "..."}
    API->>Agent: process_question()
    
    Note over Agent: Step 1: THOUGHT<br/>Detect intent, extract month entities, verify domain
    
    Note over Agent: Step 2: ACTION<br/>Formulate analytical query for monthly revenue aggregation
    Agent->>Validator: validate_and_sanitize(SQL)
    
    alt SQL contains destructive keyword or invalid table
        Validator-->>Agent: Violation Detected (Security Rejection)
        Agent-->>API: Safe rejection message
    else Query is Safe SELECT
        Validator-->>Agent: Query Approved with safety LIMIT
        Agent->>DB: execute_query(sanitized_sql)
        DB-->>Agent: Step 3: OBSERVATION (6 monthly rowsets)
    end

    Note over Agent: Step 4: SYNTHESIS<br/>Calculate MoM %, identify peak month, bind KPIs to numbers
    Agent-->>API: Return structured answer, KPIs, table data & chart config
    API-->>UI: JSON Payload (answer, sql, chart, trace, latency)
    UI-->>User: Displays Executive Narrative, Line Chart, and SQL Trace
```

---

## 3. Defense-in-Depth SQL Security
To satisfy strict enterprise security requirements and eliminate risk of data tampering or SQL injection:

1. **Token & AST Inspection (`SQLValidator`)**:
   - Every statement is parsed using `sqlparse`.
   - Piggyback / multi-statement queries (`SELECT ...; DROP TABLE ...`) are rejected immediately.
   - Prohibits non-`SELECT` statement types (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `CREATE`, `REPLACE`, `ATTACH`, `DETACH`, `TRUNCATE`, `EXEC`, `PRAGMA`, `GRANT`, `REVOKE`).

2. **Schema Entity Whitelisting**:
   - Queries are only permitted to reference explicit analytical entities: `sales_transactions`, `v_completed_sales`, and `data_quality_audit`.
   - Access to internal SQLite tables (`sqlite_master`, `sqlite_sequence`) is denied.

3. **Database Engine Enforcement**:
   - Every analytical connection is initialized with:
     ```sql
     PRAGMA query_only = ON;
     ```
   - Even if a malicious command bypassed software regex and AST validation, SQLite's storage engine will throw a fatal `sqlite3.OperationalError: attempt to write a readonly database`.

4. **Resource Bounds**:
   - If a query lacks an explicit `LIMIT` clause, `SQLValidator` automatically appends `LIMIT 1000` to prevent memory exhaustion and Denial-of-Service.

---

## 4. Preventing Hallucinations & Incorrect Answers

| Challenge | Prevention Mechanism |
| :--- | :--- |
| **Hallucinated numbers** | Answers are synthesized strictly from the executed query's rowset. Numbers are formatted directly from database aggregates. |
| **Invalid question types** | Out-of-domain questions (e.g. weather, politics, recipes) trigger guardrails that redirect the user to business intelligence topics. |
| **Data anomalies & dirty data** | ETL pipeline automatically imputes missing catalog prices, flags returned items, detects zero quantities, and logs every action in `data_quality_audit`. |
| **Full auditability** | Every response exposes the exact SQL query executed, the latency in milliseconds, and the step-by-step ReAct reasoning trace. |
