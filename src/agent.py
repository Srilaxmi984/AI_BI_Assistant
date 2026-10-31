"""
agent.py — ReAct Agent coordinator.

Order of checks per question:
  1. Max-length guard  (>500 chars → 422 via api.py; also checked here)
  2. Attack-pattern guard (SQL-injection sequences in the question text)
  3. Out-of-domain guard (known irrelevant keywords)
  4. LLM path (if key + LLM_ENABLED and intent=="unknown"):
       a. LLM returns "OUT_OF_SCOPE" → out_of_domain, mode=none        [fix #5]
       b. LLM returns valid SQL → validate → execute → success, mode=llm
       c. Retry once with the validation error appended                [fix #2]
       d. Retry fails → fall through
  5. "Can't answer" gate: unknown intent + LLM unavailable + no named
       exploratory keyword → clear "I can't answer" message, mode=none  [fix #4]
  6. Named exploratory SQL branches (category / channel / discount / …)
  7. Deterministic engine for the 5 benchmarks

All SQL goes through database.execute_query() which calls
SQLValidator.validate_and_sanitize — the single choke point.
"""

import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.config import ALLOWED_TABLES
from src.database import DatabaseManager
from src.sql_validator import SQLValidator, SQLValidationError
from src.analytical_engine import AnalyticalEngine

logger = logging.getLogger("BIAssistant")

# ---------------------------------------------------------------------------
# Attack-pattern guard — SQL injection sequences in the *question text*.
# Only clear injection patterns (not innocent business words) are blocked.
# "Show me the revenue update for May" must still be answered.
# ---------------------------------------------------------------------------
_SQL_ATTACK_PATTERNS = re.compile(
    r"""(
        drop\s+table
      | delete\s+from
      | insert\s+into
      | update\s+\w+\s+set
      | truncate\s+table
      | alter\s+table
      | ;\s*(?:drop|delete|insert|update|truncate|alter|create)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

MAX_QUESTION_LENGTH = 500

# Keywords that match a named exploratory SQL branch
_EXPLORATORY_KEYWORDS = frozenset({
    "category", "categories", "channel", "online", "retail",
    "discount", "return", "audit", "data quality", "missing",
    "invalid", "average", "aov", "unit", "quantity", "how many items",
})


class SalesBIAgent:
    """
    Business Intelligence Agent — ReAct loop with LLM + deterministic fallback.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        self.analytical_engine = AnalyticalEngine(self.db)
        self.validator = SQLValidator()   # instance used for fix #1

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process_question(self, question: str) -> Dict[str, Any]:
        """
        Main ReAct loop.  Returns a response dict that maps directly to
        QueryResponse (including the 'mode' field).
        """
        start_time = time.time()
        steps: List[Dict[str, str]] = []

        # ── 0. Empty / blank ──────────────────────────────────────────
        if not question or not question.strip():
            return self._build_response(
                question="",
                answer="Please ask a question regarding sales, revenue, products, or regional trends.",
                sql_query="", supporting_figures={}, table_data=[],
                chart_type=None, chart_config=None,
                steps=[{"step": "Thought", "detail": "Empty query provided."}],
                status="invalid_request", mode="none", start_time=start_time,
            )

        q = question.strip()

        # ── 1. Max length ─────────────────────────────────────────────
        if len(q) > MAX_QUESTION_LENGTH:
            return self._build_response(
                question=q,
                answer=f"Question is too long ({len(q)} chars). Please keep it under {MAX_QUESTION_LENGTH} characters.",
                sql_query="", supporting_figures={}, table_data=[],
                chart_type=None, chart_config=None,
                steps=[{"step": "Guard", "detail": "Question exceeds max length."}],
                status="invalid_request", mode="none", start_time=start_time,
            )

        # ── 2. Attack-pattern guard ───────────────────────────────────
        if _SQL_ATTACK_PATTERNS.search(q):
            steps.append({"step": "Guard", "detail": "SQL attack pattern detected in question text."})
            return self._build_response(
                question=q,
                answer=(
                    "Your question contains SQL command patterns (e.g. 'DROP TABLE', 'DELETE FROM') "
                    "that are not permitted. Please ask a plain business question about sales data."
                ),
                sql_query="", supporting_figures={}, table_data=[],
                chart_type=None, chart_config=None,
                steps=steps, status="rejected", mode="none", start_time=start_time,
            )

        # ── 3. Intent detection ───────────────────────────────────────
        intent, params = self.analytical_engine.detect_intent(q)
        steps.append({
            "step": "Thought",
            "detail": f"Analysing '{q}'. Detected intent: '{intent}' with params: {params}."
        })

        # ── 4. Out-of-domain guard ────────────────────────────────────
        _irrelevant = ["weather", "capital of", "recipe", "poem", "sports",
                       "movie", "president", "joke"]
        if any(w in q.lower() for w in _irrelevant) and intent == "unknown":
            steps.append({"step": "Guard", "detail": "Out-of-domain question."})
            return self._build_response(
                question=q,
                answer=(
                    "I am a Sales Business Intelligence Assistant specialized in analysing sales "
                    "transactions, product revenue, regional performance, and monthly trends. "
                    "Please ask a sales-related question."
                ),
                sql_query="", supporting_figures={}, table_data=[],
                chart_type=None, chart_config=None,
                steps=steps, status="out_of_domain", mode="none", start_time=start_time,
            )

        # ── 5. LLM path (unknown intent only) ────────────────────────
        if intent == "unknown":
            llm_result = self._try_llm(q, steps, start_time)
            if llm_result is not None:
                return llm_result

            # LLM unavailable / exhausted → check for named exploratory keywords
            # before falling through.  [fix #4]
            q_lower = q.lower()
            if not any(w in q_lower for w in _EXPLORATORY_KEYWORDS):
                steps.append({"step": "Fallback", "detail": "LLM unavailable and question not recognised."})
                return self._build_response(
                    question=q,
                    answer=(
                        "I can't answer that question with the available sales data. "
                        "Try asking about total revenue, products, regions, monthly trends, "
                        "discounts, returns, or sales channels."
                    ),
                    sql_query="", supporting_figures={}, table_data=[],
                    chart_type="table", chart_config=None,
                    steps=steps, status="out_of_domain", mode="none", start_time=start_time,
                )

        # ── 6. Deterministic engine ───────────────────────────────────
        try:
            result, mode = self._run_deterministic(intent, params, q, steps, start_time)
        except Exception as exc:
            logger.exception("Deterministic engine error for question: %s", q)  # fix #6: log real exc
            steps.append({"step": "Error", "detail": "Deterministic engine encountered an error."})
            return self._build_response(
                question=q,
                answer="An internal error occurred. Please try a different question.",  # fix #6: no raw exc
                sql_query="", supporting_figures={}, table_data=[],
                chart_type=None, chart_config=None,
                steps=steps, status="error", mode="none", start_time=start_time,
            )

        steps.append({"step": "Synthesis", "detail": "Generating executive answer from query results."})
        return self._build_response(
            question=q,
            answer=result.get("answer", ""),
            sql_query=result.get("sql_query", ""),
            supporting_figures=result.get("supporting_figures", {}),
            table_data=result.get("table_data", []),
            chart_type=result.get("chart_type"),
            chart_config=result.get("chart_config"),
            steps=steps, status="success", mode=mode, start_time=start_time,
        )

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------

    def _try_llm(self, question: str, steps: list, start_time: float) -> Optional[Dict[str, Any]]:
        """
        Attempt to answer via LLM text-to-SQL.
        Returns a full response dict on success, None if LLM is unavailable
        or all retries are exhausted.
        """
        try:
            from src.llm_client import LLMClient, LLMDisabledError, LLMGenerationError
        except ImportError:
            return None

        try:
            client = LLMClient()
        except Exception:
            return None  # key missing / LLM disabled — silent fallback

        steps.append({"step": "Thought", "detail": "Unknown intent — attempting LLM text-to-SQL."})

        last_error = ""   # fix #7: local variable, not a class attribute

        for attempt in range(1, 3):   # max 2 attempts (1 retry with error appended)
            # fix #2: append error hint on retry; schema always lives in system prompt
            error_hint = f"\nPrevious SQL was rejected: {last_error}" if last_error else ""

            try:
                sql = client.generate_sql(question, error_hint)
            except Exception as exc:
                logger.warning("LLM generate_sql failed (attempt %d): %s", attempt, exc)
                steps.append({"step": "LLM Error", "detail": f"Attempt {attempt}: LLM call failed."})
                break   # fall back to deterministic

            steps.append({"step": "LLM Action", "detail": f"Attempt {attempt}: LLM returned a response."})

            # fix #5: check for OUT_OF_SCOPE sentinel before SQL validation
            if sql.strip().upper() == "OUT_OF_SCOPE":
                steps.append({"step": "LLM", "detail": "LLM indicated question is out of scope."})
                return self._build_response(
                    question=question,
                    answer=(
                        "I am a Sales Business Intelligence Assistant — I can only answer "
                        "questions about sales transactions, revenue, products, regions, and trends."
                    ),
                    sql_query="", supporting_figures={}, table_data=[],
                    chart_type="table", chart_config=None,
                    steps=steps, status="out_of_domain", mode="none", start_time=start_time,
                )

            # fix #1: use self.validator instance, not the class
            is_valid, sanitized_sql, error_msg = self.validator.validate_and_sanitize(sql)
            if not is_valid:
                last_error = error_msg   # fix #7
                steps.append({"step": "Validator", "detail": f"Attempt {attempt} rejected: {error_msg}"})
                if attempt == 1:
                    continue   # retry once with error fed back
                break          # give up

            try:
                rows = self.db.execute_query(sanitized_sql)
            except SQLValidationError as exc:
                last_error = str(exc)   # fix #7
                steps.append({"step": "Validator", "detail": f"Execution blocked (attempt {attempt})."})
                if attempt == 1:
                    continue
                break
            except Exception as exc:
                logger.warning("LLM query execution failed (attempt %d): %s", attempt, exc)  # fix #6
                last_error = str(exc)
                steps.append({"step": "Error", "detail": f"Attempt {attempt}: query execution failed."})
                if attempt == 1:
                    continue
                break

            steps.append({"step": "Observation", "detail": f"LLM query returned {len(rows)} row(s)."})
            answer, chart_type, chart_config, supporting_figures = _format_rows(rows, sanitized_sql)
            steps.append({"step": "Synthesis", "detail": "Building answer from returned rows."})
            return self._build_response(
                question=question, answer=answer, sql_query=sanitized_sql,
                supporting_figures=supporting_figures, table_data=rows,
                chart_type=chart_type, chart_config=chart_config,
                steps=steps, status="success", mode="llm", start_time=start_time,
            )

        steps.append({"step": "Fallback", "detail": "LLM path exhausted — using deterministic engine."})
        return None

    # ------------------------------------------------------------------
    # Deterministic engine dispatcher
    # ------------------------------------------------------------------

    def _run_deterministic(
        self, intent: str, params: dict, question: str,
        steps: list, start_time: float
    ) -> Tuple[Dict[str, Any], str]:
        """
        Dispatches to the appropriate AnalyticalEngine method or named
        exploratory SQL branches. Returns (result_dict, mode_str).
        """
        if intent == "total_revenue":
            steps.append({"step": "Action", "detail": "Deterministic: get_total_revenue()"})
            result = self.analytical_engine.get_total_revenue()
            steps.append({"step": "Observation",
                          "detail": f"Net revenue: ${result['supporting_figures']['total_net_revenue']:,.2f}"})

        elif intent in ("product_revenue", "highest_revenue_product"):
            steps.append({"step": "Action", "detail": "Deterministic: get_highest_revenue_product()"})
            result = self.analytical_engine.get_highest_revenue_product()
            steps.append({"step": "Observation",
                          "detail": f"Top product: {result['supporting_figures']['top_product']}"})

        elif intent == "monthly_revenue_trend":
            steps.append({"step": "Action", "detail": "Deterministic: get_monthly_revenue_trend()"})
            result = self.analytical_engine.get_monthly_revenue_trend()
            steps.append({"step": "Observation",
                          "detail": f"Trend over {len(result['table_data'])} months."})

        elif intent in ("region_sales", "highest_sales_region"):
            steps.append({"step": "Action", "detail": "Deterministic: get_highest_sales_region()"})
            result = self.analytical_engine.get_highest_sales_region()
            steps.append({"step": "Observation",
                          "detail": f"Top region: {result['supporting_figures']['top_region']}"})

        elif intent == "revenue_change_between_months":
            m1 = params.get("m1", "2026-01")
            m2 = params.get("m2", "2026-02")
            steps.append({"step": "Action", "detail": f"Deterministic: compare {m1} vs {m2}"})
            result = self.analytical_engine.get_revenue_change_between_months(m1, m2)
            steps.append({"step": "Observation",
                          "detail": f"Change: {result['supporting_figures']['direction']} "
                                    f"${abs(result['supporting_figures']['absolute_change']):,.2f}"})
        elif intent == "breakdown":
            spec = params["spec"]
            steps.append({"step": "Action", "detail": f"Deterministic: verified breakdown (measure={spec.metric}, group by={spec.dimension}, filters={spec.filters})"})
            result = self.analytical_engine.breakdown.run(spec)
            steps.append({"step": "Observation", "detail": f"{len(result.get('table_data', []))} row(s) returned."})

        else:
            # Named exploratory SQL branches — guaranteed to have a keyword match
            # (unknown intent with no keyword is already turned away before here)
            result = self._run_exploratory(question, steps)

        return result, "deterministic"

    # ------------------------------------------------------------------
    # Named exploratory SQL branches
    # ------------------------------------------------------------------

    def _run_exploratory(self, question: str, steps: list) -> Dict[str, Any]:
        q = question.lower()
        steps.append({"step": "Thought", "detail": "Named exploratory branch selected."})

        if "category" in q or "categories" in q:
            sql = ("SELECT category, SUM(quantity) AS total_units, SUM(net_revenue) AS total_revenue "
                   "FROM v_completed_sales GROUP BY category ORDER BY total_revenue DESC;")
        elif "channel" in q or "online" in q or "retail" in q:
            sql = ("SELECT sales_channel, COUNT(*) AS transactions, SUM(quantity) AS total_units, "
                   "SUM(net_revenue) AS total_revenue "
                   "FROM v_completed_sales GROUP BY sales_channel ORDER BY total_revenue DESC;")
        elif "discount" in q:
            sql = ("SELECT product, SUM(discount_amount) AS total_discount, "
                   "SUM(gross_revenue) AS gross_revenue, SUM(net_revenue) AS total_revenue "
                   "FROM v_completed_sales WHERE discount_amount > 0 "
                   "GROUP BY product ORDER BY total_discount DESC;")
        elif "return" in q:
            sql = ("SELECT transaction_id, order_date, product, quantity, unit_price, "
                   "gross_revenue, status FROM sales_transactions WHERE status = 'Returned';")
        elif "audit" in q or "data quality" in q or "missing" in q or "invalid" in q:
            sql = ("SELECT transaction_id, issue_type, description, action_taken, timestamp "
                   "FROM data_quality_audit;")
        elif "average" in q or "aov" in q:
            sql = ("SELECT COUNT(*) AS total_completed_orders, SUM(quantity) AS total_units_sold, "
                   "SUM(net_revenue) AS total_revenue, "
                   "ROUND(AVG(net_revenue), 2) AS avg_order_value FROM v_completed_sales;")
        else:  # "unit" / "quantity" / "how many items"
            sql = ("SELECT COUNT(*) AS total_completed_orders, SUM(quantity) AS total_units_sold, "
                   "SUM(net_revenue) AS total_revenue FROM v_completed_sales;")

        steps.append({"step": "Action", "detail": "Running named exploratory query."})
        rows = self.db.execute_query(sql)
        steps.append({"step": "Observation", "detail": f"Query returned {len(rows)} row(s)."})

        if "category" in q:
            cat_summary = ", ".join([f"{r['category']}: ${r['total_revenue']:,.2f}" for r in rows])
            answer = f"Sales breakdown by product category: {cat_summary}."
            chart_type = "bar"
            chart_config = {"labels": [r["category"] for r in rows],
                            "values": [r["total_revenue"] for r in rows],
                            "series_name": "Category Revenue ($)"}
        elif "channel" in q:
            chan_summary = ", ".join([f"{r['sales_channel']}: ${r['total_revenue']:,.2f}" for r in rows])
            answer = f"Sales breakdown by channel: {chan_summary}."
            chart_type = "bar"
            chart_config = {"labels": [r["sales_channel"] for r in rows],
                            "values": [r["total_revenue"] for r in rows],
                            "series_name": "Channel Revenue ($)"}
        elif "discount" in q:
            total_disc = sum(r["total_discount"] for r in rows)
            disc_summary = ", ".join([f"{r['product']}: ${r['total_discount']:,.2f}" for r in rows])
            answer = f"Total discounts granted: **${total_disc:,.2f}** ({disc_summary})."
            chart_type = "bar"
            chart_config = {"labels": [r["product"] for r in rows],
                            "values": [r["total_discount"] for r in rows],
                            "series_name": "Discounts ($)"}
        elif "return" in q:
            if rows:
                r0 = rows[0]
                answer = (f"There is {len(rows)} returned order: "
                          f"Transaction {r0['transaction_id']} "
                          f"({r0['product']} x {r0['quantity']} units, ${r0['gross_revenue']:,.2f}).")
            else:
                answer = "No returned orders found."
            chart_type, chart_config = "table", None
        elif "audit" in q or "quality" in q or "missing" in q:
            answer = f"The dataset has {len(rows)} logged data quality events."
            chart_type, chart_config = "table", None
        elif "average" in q or "aov" in q:
            aov = rows[0].get("avg_order_value", 0.0) if rows else 0.0
            total_rev = rows[0].get("total_revenue", 0.0) if rows else 0.0
            total_orders = rows[0].get("total_completed_orders", 0) if rows else 0
            answer = (f"The average order value (AOV) across {total_orders} completed "
                      f"transactions is **${aov:,.2f}** (total revenue: ${total_rev:,.2f}).")
            chart_type, chart_config = "metric_card", None
        else:
            units = rows[0].get("total_units_sold", 0) if rows else 0
            orders = rows[0].get("total_completed_orders", 0) if rows else 0
            answer = f"A total of **{units:,} units** were sold across {orders} completed orders."
            chart_type, chart_config = "metric_card", None

        return {
            "sql_query": sql,
            "answer": answer,
            "supporting_figures": rows[0] if rows else {},
            "table_data": rows,
            "chart_type": chart_type,
            "chart_config": chart_config,
        }

    # ------------------------------------------------------------------
    # Response builder
    # ------------------------------------------------------------------

    def _build_response(
        self, question, answer, sql_query, supporting_figures,
        table_data, chart_type, chart_config, steps, status, mode, start_time
    ) -> Dict[str, Any]:
        return {
            "question": question,
            "answer": answer,
            "sql_query": sql_query or "",
            "supporting_figures": supporting_figures,
            "table_data": table_data,
            "chart_type": chart_type or "table",
            "chart_config": chart_config,
            "reasoning_trace": steps,
            "execution_time_ms": round((time.time() - start_time) * 1000, 2),
            "data_quality_note": (
                "Calculations reflect completed sales. "
                "1 missing unit price (TXN0051) was imputed with catalog price $1,200."
            ),
            "status": status,
            "mode": mode,
        }


# ---------------------------------------------------------------------------
# Generic row formatter for LLM-generated results  (fix #3)
# ---------------------------------------------------------------------------

# Column-name tokens that indicate a currency value
_MONEY_TOKENS = frozenset({"revenue", "amount", "price", "discount", "gross", "net", "cost", "sales"})
# Column-name tokens that indicate a percentage value
_PCT_TOKENS = frozenset({"pct", "percent", "percentage", "rate", "ratio"})
# Column-name tokens that indicate a time series
_TIME_TOKENS = frozenset({"year_month", "month", "date", "period", "week", "quarter"})


def _fmt(col_name: str, val: Any) -> str:
    """Format val based on the column name semantics.  Fix #3."""
    col = col_name.lower()
    if isinstance(val, (int, float)):
        if any(t in col for t in _MONEY_TOKENS):
            return f"${val:,.2f}" if isinstance(val, float) else f"${val:,}"
        if any(t in col for t in _PCT_TOKENS):
            return f"{val:.2f}%"
        return f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"
    return str(val)


def _is_time_series(keys: List[str]) -> bool:
    """Return True if the first column looks like a time dimension.  Fix #3."""
    col = keys[0].lower()
    return any(t in col for t in _TIME_TOKENS)


def _format_rows(
    rows: List[Dict[str, Any]], sql: str
) -> Tuple[str, str, Optional[Dict], Dict[str, Any]]:
    """
    Builds a plain-English answer, chart type, chart config, and
    supporting_figures from LLM-generated query rows.
    The LLM never writes numbers — Python does.  Fix #3.
    """
    if not rows:
        return "The query returned no results.", "table", None, {}

    first = rows[0]
    keys = list(first.keys())

    # Single-row, single-value (e.g. SUM → total)
    if len(rows) == 1 and len(keys) == 1:
        col = keys[0]
        answer = f"Result: **{col}** = {_fmt(col, first[col])}"
        return answer, "metric_card", None, first

    # Single-row, multiple values (aggregate summary)
    if len(rows) == 1:
        parts = [f"{k}: {_fmt(k, v)}" for k, v in first.items()]
        answer = "Summary — " + ", ".join(parts) + "."
        return answer, "metric_card", None, first

    # Multiple rows — find label column and primary value column
    label_col = keys[0]
    value_cols = [k for k in keys[1:] if isinstance(first.get(k), (int, float))]
    value_col = value_cols[-1] if value_cols else keys[-1]  # prefer last numeric (often revenue)

    # fix #3: time-series → report first, last, peak; choose line chart from column names
    if _is_time_series(keys):
        chart_type = "line"
        first_row = rows[0]
        last_row = rows[-1]
        peak_row = max(rows, key=lambda r: (r.get(value_col) or 0))
        answer = (
            f"Time series ({len(rows)} periods): "
            f"first {_fmt(value_col, first_row[value_col])} ({first_row[label_col]}), "
            f"last {_fmt(value_col, last_row[value_col])} ({last_row[label_col]}), "
            f"peak {_fmt(value_col, peak_row[value_col])} ({peak_row[label_col]})."
        )
    else:
        chart_type = "bar"
        top = rows[0]
        answer = (
            f"Top result: **{top[label_col]}** with {value_col} = {_fmt(value_col, top[value_col])}. "
            f"({len(rows)} rows returned.)"
        )

    chart_config = {
        "labels": [str(r[label_col]) for r in rows],
        "values": [r.get(value_col, 0) for r in rows],
        "series_name": value_col,
    }

    return answer, chart_type, chart_config, first
