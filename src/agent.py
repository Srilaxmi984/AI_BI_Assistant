"""
agent.py — ReAct Agent coordinator.

Order of checks per question:
  1. Max length guard  (>500 chars → caller raises 422 via api.py)
  2. Attack-pattern guard (SQL-injection keywords in question text → rejected)
  3. Out-of-domain guard
  4. LLM path (if key + LLM_ENABLED): generate SQL → validate → execute
       on failure: retry once with error, then fall back to deterministic
  5. Deterministic engine (guaranteed fallback)

All SQL executed through DatabaseManager.execute_query(), which runs
SQLValidator at a single choke point — agent.py never calls db.execute_query()
with un-validated SQL.
"""

import re
import time
import logging
from typing import Dict, Any, List, Optional, Tuple

from src.config import ALLOWED_TABLES
from src.database import DatabaseManager
from src.sql_validator import SQLValidator, SQLValidationError
from src.analytical_engine import AnalyticalEngine

logger = logging.getLogger("BIAssistant")

# ---------------------------------------------------------------------------
# Attack-pattern guard: SQL keyword sequences in the question text itself.
# We only block clear SQL-injection patterns, not innocent business words.
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


class SalesBIAgent:
    """
    Business Intelligence Agent — ReAct loop with LLM + deterministic fallback.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        self.analytical_engine = AnalyticalEngine(self.db)
        self.validator = SQLValidator()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process_question(self, question: str) -> Dict[str, Any]:
        """
        Main ReAct loop.  Returns a response dict that maps directly to
        QueryResponse (including the new 'mode' field).
        """
        start_time = time.time()
        steps: List[Dict[str, str]] = []

        # ── 0. Empty / blank ──────────────────────────────────────────
        if not question or not question.strip():
            return self._build_response(
                question="",
                answer="Please ask a question regarding sales, revenue, products, or regional trends.",
                sql_query="",
                supporting_figures={},
                table_data=[],
                chart_type=None,
                chart_config=None,
                steps=[{"step": "Thought", "detail": "Empty query provided."}],
                status="invalid_request",
                mode="none",
                start_time=start_time,
            )

        q = question.strip()

        # ── 1. Max length (checked here for agent-level callers; api.py
        #       also enforces this via HTTP 422 for REST clients) ───────
        if len(q) > MAX_QUESTION_LENGTH:
            return self._build_response(
                question=q,
                answer=f"Question is too long ({len(q)} chars). Please keep it under {MAX_QUESTION_LENGTH} characters.",
                sql_query="",
                supporting_figures={},
                table_data=[],
                chart_type=None,
                chart_config=None,
                steps=[{"step": "Guard", "detail": "Question exceeds max length."}],
                status="invalid_request",
                mode="none",
                start_time=start_time,
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
                sql_query="",
                supporting_figures={},
                table_data=[],
                chart_type=None,
                chart_config=None,
                steps=steps,
                status="rejected",
                mode="none",
                start_time=start_time,
            )

        # ── 3. Intent detection ───────────────────────────────────────
        intent, params = self.analytical_engine.detect_intent(q)
        steps.append({
            "step": "Thought",
            "detail": f"Analysing '{q}'. Detected intent: '{intent}' with params: {params}."
        })

        # ── 4. Out-of-domain guard ────────────────────────────────────
        irrelevant_keywords = ["weather", "capital of", "recipe", "poem", "sports",
                               "movie", "president", "joke"]
        if any(w in q.lower() for w in irrelevant_keywords) and intent == "unknown":
            steps.append({"step": "Guard", "detail": "Out-of-domain question."})
            return self._build_response(
                question=q,
                answer=(
                    "I am a Sales Business Intelligence Assistant specialized in analysing sales "
                    "transactions, product revenue, regional performance, and monthly trends. "
                    "Please ask a sales-related question."
                ),
                sql_query="",
                supporting_figures={},
                table_data=[],
                chart_type=None,
                chart_config=None,
                steps=steps,
                status="out_of_domain",
                mode="none",
                start_time=start_time,
            )

        # ── 5. LLM path (when a key is available and intent is unknown) ──
        #       For known intents we use the deterministic engine directly;
        #       for unknown intents we first try the LLM.
        mode = "deterministic"

        if intent == "unknown":
            llm_result = self._try_llm(q, steps, start_time)
            if llm_result is not None:
                return llm_result
            # LLM unavailable or failed — fall through to deterministic

        # ── 6. Deterministic engine ───────────────────────────────────
        try:
            result, mode_used = self._run_deterministic(intent, params, q, steps, start_time)
            mode = mode_used
        except Exception as exc:
            logger.exception("Deterministic engine error")
            steps.append({"step": "Error", "detail": str(exc)})
            return self._build_response(
                question=q,
                answer=f"An error occurred: {exc}",
                sql_query="",
                supporting_figures={},
                table_data=[],
                chart_type=None,
                chart_config=None,
                steps=steps,
                status="error",
                mode="none",
                start_time=start_time,
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
            steps=steps,
            status="success",
            mode=mode,
            start_time=start_time,
        )

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------

    def _try_llm(self, question: str, steps: list, start_time: float) -> Optional[Dict[str, Any]]:
        """
        Attempt to answer via LLM text-to-SQL.
        Returns a full response dict on success, None if LLM is unavailable,
        or falls back to deterministic on repeated failure.
        """
        try:
            from src.llm_client import LLMClient, LLMDisabledError, LLMGenerationError
        except ImportError:
            return None

        try:
            client = LLMClient()
        except Exception:
            # Key missing / LLM disabled — silent fallback
            return None

        steps.append({"step": "Thought", "detail": "Unknown intent — attempting LLM text-to-SQL."})

        for attempt in range(1, 3):   # max 2 attempts (1 retry with error feedback)
            try:
                schema_hint = ""
                if attempt == 2:
                    schema_hint = f"\nPrevious attempt failed validation: {self._last_llm_error}"
                sql = client.generate_sql(question, schema_hint)
            except Exception as exc:
                steps.append({"step": "LLM Error", "detail": f"Attempt {attempt}: {exc}"})
                break   # fall back to deterministic

            steps.append({"step": "LLM Action", "detail": f"Attempt {attempt}: LLM generated SQL."})

            # Validate (choke point — also runs inside db.execute_query,
            # but we catch here to enable retry)
            is_valid, sanitized_sql, error_msg = SQLValidator.validate_and_sanitize(sql)
            if not is_valid:
                self._last_llm_error = error_msg
                steps.append({"step": "Validator", "detail": f"Attempt {attempt} rejected: {error_msg}"})
                if attempt == 1:
                    continue   # retry once with error fed back to LLM
                break          # give up, fall back to deterministic

            # Execute (validator runs again inside db.execute_query — harmless double-check)
            try:
                rows = self.db.execute_query(sanitized_sql)
            except SQLValidationError as exc:
                self._last_llm_error = str(exc)
                steps.append({"step": "Validator", "detail": f"Execution blocked: {exc}"})
                if attempt == 1:
                    continue
                break
            except Exception as exc:
                steps.append({"step": "Error", "detail": f"Attempt {attempt} execution: {exc}"})
                if attempt == 1:
                    self._last_llm_error = str(exc)
                    continue
                break

            steps.append({"step": "Observation", "detail": f"LLM query returned {len(rows)} row(s)."})
            answer, chart_type, chart_config, supporting_figures = _format_rows(question, rows, sanitized_sql)

            steps.append({"step": "Synthesis", "detail": "Building answer from returned rows."})
            return self._build_response(
                question=question,
                answer=answer,
                sql_query=sanitized_sql,
                supporting_figures=supporting_figures,
                table_data=rows,
                chart_type=chart_type,
                chart_config=chart_config,
                steps=steps,
                status="success",
                mode="llm",
                start_time=start_time,
            )

        # All attempts failed — fall through to deterministic
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
        Dispatches to the appropriate AnalyticalEngine method or the
        hard-coded exploratory SQL branches. Returns (result_dict, mode_str).
        """
        if intent == "total_revenue":
            steps.append({"step": "Action", "detail": "Deterministic: get_total_revenue()"})
            result = self.analytical_engine.get_total_revenue()
            steps.append({"step": "Observation", "detail": f"Net revenue: ${result['supporting_figures']['total_net_revenue']:,.2f}"})

        elif intent in ("product_revenue", "highest_revenue_product"):
            steps.append({"step": "Action", "detail": "Deterministic: get_highest_revenue_product()"})
            result = self.analytical_engine.get_highest_revenue_product()
            steps.append({"step": "Observation", "detail": f"Top product: {result['supporting_figures']['top_product']}"})

        elif intent == "monthly_revenue_trend":
            steps.append({"step": "Action", "detail": "Deterministic: get_monthly_revenue_trend()"})
            result = self.analytical_engine.get_monthly_revenue_trend()
            steps.append({"step": "Observation", "detail": f"Trend over {len(result['table_data'])} months."})

        elif intent in ("region_sales", "highest_sales_region"):
            steps.append({"step": "Action", "detail": "Deterministic: get_highest_sales_region()"})
            result = self.analytical_engine.get_highest_sales_region()
            steps.append({"step": "Observation", "detail": f"Top region: {result['supporting_figures']['top_region']}"})

        elif intent == "revenue_change_between_months":
            m1 = params.get("m1", "2026-01")
            m2 = params.get("m2", "2026-02")
            steps.append({"step": "Action", "detail": f"Deterministic: compare {m1} vs {m2}"})
            result = self.analytical_engine.get_revenue_change_between_months(m1, m2)
            steps.append({"step": "Observation", "detail": f"Change: {result['supporting_figures']['direction']} ${abs(result['supporting_figures']['absolute_change']):,.2f}"})

        else:
            # Exploratory / unknown intent — hard-coded SQL branches
            result = self._run_exploratory(question, steps)

        return result, "deterministic"

    # ------------------------------------------------------------------
    # Exploratory SQL (unchanged logic from original agent.py)
    # ------------------------------------------------------------------

    def _run_exploratory(self, question: str, steps: list) -> Dict[str, Any]:
        q = question.lower()
        steps.append({"step": "Thought", "detail": "Unknown intent — using exploratory SQL."})

        if "category" in q or "categories" in q:
            sql = "SELECT category, SUM(quantity) as total_units, SUM(net_revenue) as total_revenue FROM v_completed_sales GROUP BY category ORDER BY total_revenue DESC;"
        elif "channel" in q or "online" in q or "retail" in q:
            sql = "SELECT sales_channel, COUNT(*) as transactions, SUM(quantity) as total_units, SUM(net_revenue) as total_revenue FROM v_completed_sales GROUP BY sales_channel ORDER BY total_revenue DESC;"
        elif "discount" in q:
            sql = "SELECT product, SUM(discount_amount) as total_discount, SUM(gross_revenue) as gross_revenue, SUM(net_revenue) as net_revenue FROM v_completed_sales WHERE discount_amount > 0 GROUP BY product ORDER BY total_discount DESC;"
        elif "return" in q:
            sql = "SELECT transaction_id, order_date, product, quantity, unit_price, gross_revenue, status FROM sales_transactions WHERE status = 'Returned';"
        elif "audit" in q or "data quality" in q or "missing" in q or "invalid" in q:
            sql = "SELECT transaction_id, issue_type, description, action_taken, timestamp FROM data_quality_audit;"
        else:
            sql = "SELECT COUNT(*) as total_completed_orders, SUM(quantity) as total_units_sold, SUM(net_revenue) as total_revenue, ROUND(AVG(net_revenue), 2) as avg_order_value FROM v_completed_sales;"

        # Validation happens inside db.execute_query — just execute
        steps.append({"step": "Action", "detail": f"Exploratory query selected."})
        rows = self.db.execute_query(sql)
        steps.append({"step": "Observation", "detail": f"Query returned {len(rows)} row(s)."})

        # Format answer (same logic as original)
        if "category" in q:
            cat_summary = ", ".join([f"{r['category']}: ${r['total_revenue']:,.2f}" for r in rows])
            answer = f"Sales breakdown by product category: {cat_summary}."
            chart_type, chart_config = "bar", {"labels": [r["category"] for r in rows], "values": [r["total_revenue"] for r in rows], "series_name": "Category Revenue ($)"}
        elif "channel" in q:
            chan_summary = ", ".join([f"{r['sales_channel']}: ${r['total_revenue']:,.2f}" for r in rows])
            answer = f"Sales breakdown by channel: {chan_summary}."
            chart_type, chart_config = "bar", {"labels": [r["sales_channel"] for r in rows], "values": [r["total_revenue"] for r in rows], "series_name": "Channel Revenue ($)"}
        elif "discount" in q:
            total_disc = sum(r["total_discount"] for r in rows)
            disc_summary = ", ".join([f"{r['product']}: ${r['total_discount']:,.2f}" for r in rows])
            answer = f"Total discounts granted amount to **${total_disc:,.2f}** ({disc_summary})."
            chart_type, chart_config = "bar", {"labels": [r["product"] for r in rows], "values": [r["total_discount"] for r in rows], "series_name": "Discounts ($)"}
        elif "return" in q:
            answer = f"There is {len(rows)} returned order in the dataset: Transaction {rows[0]['transaction_id']} ({rows[0]['product']} x {rows[0]['quantity']} units, ${rows[0]['gross_revenue']:,.2f})."
            chart_type, chart_config = "table", None
        elif "audit" in q or "quality" in q or "missing" in q:
            answer = f"The dataset has {len(rows)} logged data quality events."
            chart_type, chart_config = "table", None
        elif "average" in q or "aov" in q:
            aov = rows[0].get("avg_order_value", 0.0)
            total_rev = rows[0].get("total_revenue", 0.0)
            total_orders = rows[0].get("total_completed_orders", 0)
            answer = f"The average order value (AOV) across {total_orders} completed transactions is **${aov:,.2f}** (Total revenue: ${total_rev:,.2f})."
            chart_type, chart_config = "metric_card", None
        elif "unit" in q or "quantity" in q or "how many items" in q:
            units = rows[0].get("total_units_sold", 0)
            orders = rows[0].get("total_completed_orders", 0)
            answer = f"A total of **{units} units** were sold across {orders} completed orders."
            chart_type, chart_config = "metric_card", None
        else:
            rev = rows[0].get("total_revenue", 0.0)
            units = rows[0].get("total_units_sold", 0)
            answer = f"Found {rows[0].get('total_completed_orders', 0)} completed orders generating **${rev:,.2f}** across {units} units."
            chart_type, chart_config = "table", None

        return {
            "sql_query": sql,
            "answer": answer,
            "supporting_figures": rows[0] if rows else {},
            "table_data": rows,
            "chart_type": chart_type,
            "chart_config": chart_config,
        }

    # ------------------------------------------------------------------
    # Helpers
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

    # Track last validation error for LLM retry
    _last_llm_error: str = ""


# ---------------------------------------------------------------------------
# Generic row formatter for LLM-generated results
# ---------------------------------------------------------------------------

def _format_rows(
    question: str, rows: List[Dict[str, Any]], sql: str
) -> Tuple[str, str, Optional[Dict], Dict[str, Any]]:
    """
    Builds a plain-English answer, chart type, chart config, and
    supporting_figures from the rows returned by an LLM-generated query.
    The LLM never writes numbers — Python does.
    """
    if not rows:
        return "The query returned no results.", "table", None, {}

    first = rows[0]
    keys = list(first.keys())

    # Single-row, single-value (e.g. SUM → total)
    if len(rows) == 1 and len(keys) == 1:
        val = first[keys[0]]
        answer = f"Result: **{keys[0]}** = {_fmt(val)}"
        return answer, "metric_card", None, first

    # Single-row, multiple values (aggregate summary)
    if len(rows) == 1:
        parts = [f"{k}: {_fmt(v)}" for k, v in first.items()]
        answer = "Summary — " + ", ".join(parts) + "."
        return answer, "metric_card", None, first

    # Multiple rows — try to find a label column and a value column
    label_col = keys[0]
    value_cols = [k for k in keys[1:] if isinstance(first.get(k), (int, float))]
    if not value_cols:
        value_col = keys[-1]
    else:
        value_col = value_cols[-1]   # prefer last numeric (often revenue)

    top = rows[0]
    answer = (
        f"Top result: **{top[label_col]}** with {value_col} = {_fmt(top[value_col])}. "
        f"({len(rows)} rows returned.)"
    )

    # Decide line vs bar by question keywords
    q_lower = question.lower()
    if any(w in q_lower for w in ("trend", "month", "over time")):
        chart_type = "line"
    else:
        chart_type = "bar"

    chart_config = {
        "labels": [str(r[label_col]) for r in rows],
        "values": [r.get(value_col, 0) for r in rows],
        "series_name": value_col,
    }

    return answer, chart_type, chart_config, top


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"${v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)
