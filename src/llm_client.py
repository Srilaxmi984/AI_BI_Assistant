"""
llm_client.py — Gemini text-to-SQL client using the google-genai SDK.

Usage:
    client = LLMClient()
    sql = client.generate_sql(question, error_hint)   # returns one SQL SELECT (or OUT_OF_SCOPE)

Raises:
    LLMDisabledError   – when LLM_ENABLED=false or GOOGLE_API_KEY is empty
    LLMGenerationError – on API / network / timeout failure, or an empty reply

The model's reply is never trusted: extract_sql() pulls out one statement, and the
agent validates it (SQLValidator, inside database.py) before anything runs.
"""

import re
import logging
from google import genai
from google.genai import types as genai_types

from src.config import GOOGLE_API_KEY, LLM_MODEL, LLM_ENABLED

logger = logging.getLogger("BIAssistant.LLMClient")


# --- Exceptions ----------------------------------------------------------------

class LLMDisabledError(Exception):
    """Raised when LLM_ENABLED is false or GOOGLE_API_KEY is not set."""


class LLMGenerationError(Exception):
    """Raised when the Gemini API call fails, times out, or returns nothing."""


# --- Reply cleaning ------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
# a SELECT that starts a line, up to the first semicolon or the end of the text
_LINE_SELECT_RE = re.compile(r"(?:^|\n)[ \t]*(select\b.*?)(?:;|\Z)", re.IGNORECASE | re.DOTALL)
# a SQL keyword right after a semicolon means more than one statement
_STACKED_RE = re.compile(
    r";\s*(?:drop|delete|insert|update|alter|create|truncate|attach|detach|pragma|replace|select|with)\b",
    re.IGNORECASE,
)
# fallback: the first SELECT anywhere
_ANY_SELECT_RE = re.compile(r"\bselect\b.*?(?:;|\Z)", re.IGNORECASE | re.DOTALL)


def extract_sql(text: str) -> str:
    """
    Return one SQL statement from a model reply, ignoring any explanation around it.

    - "OUT_OF_SCOPE" (with or without backticks) is returned as exactly OUT_OF_SCOPE.
    - Code fences and commentary before or after the SQL are dropped.
    - Anything that is not a SELECT (for example DROP TABLE ...) is returned unchanged,
      so the validator can reject it. Nothing dangerous is ever hidden or rewritten here.
    """
    text = (text or "").strip()
    if text.upper().strip(" .`*\n") == "OUT_OF_SCOPE":
        return "OUT_OF_SCOPE"

    fenced = _FENCE_RE.search(text)
    candidate = fenced.group(1).strip() if fenced else text

    # a second statement after a semicolon (e.g. "SELECT 1; DROP TABLE x") is passed on
    # unchanged, so the validator sees it and rejects the whole reply
    if _STACKED_RE.search(candidate):
        return candidate.strip()

    match = _LINE_SELECT_RE.search(candidate) or _ANY_SELECT_RE.search(candidate)
    if not match:
        return "OUT_OF_SCOPE" if "OUT_OF_SCOPE" in text.upper() else candidate
    statement = match.group(1) if match.re is _LINE_SELECT_RE else match.group(0)
    return statement.split("\n\n")[0].strip().rstrip(";").strip()


def _strip_fences(text: str) -> str:
    """Older helper kept for compatibility: removes ``` fences and a trailing semicolon."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip().rstrip(";").strip()


# --- System prompt -------------------------------------------------------------

_SYSTEM_PROMPT = """You are a SQL generation assistant for a SQLite sales database.

SCHEMA
------
Table: sales_transactions
  transaction_id TEXT, order_date TEXT (YYYY-MM-DD), product TEXT, category TEXT,
  region TEXT, sales_channel TEXT, quantity INTEGER, unit_price REAL,
  gross_revenue REAL, discount_amount REAL, net_revenue REAL, status TEXT,
  year_month TEXT (YYYY-MM), data_quality_flag TEXT

View:  v_completed_sales  - same columns as sales_transactions, already filtered to
       completed orders (status = 'Completed'). Use this for ALL revenue calculations.

Table: data_quality_audit
  id INTEGER, transaction_id TEXT, issue_type TEXT, description TEXT,
  action_taken TEXT, timestamp TEXT

DATA FACTS
----------
- Products: Desk, Keyboard, Laptop Stand, Monitor, Office Chair, USB-C Hub, Wireless Mouse.
- Regions: North, South, East, West. Sales channels: Online, Retail.
- Months present: 2026-01 to 2026-06 (use the year_month column, format YYYY-MM).
- net_revenue = quantity * unit_price - discount_amount.

RULES
-----
1. Revenue questions MUST use v_completed_sales and the net_revenue column.
   NEVER query sales_transactions for revenue figures.
2. Output ONLY the SQL statement itself: no markdown, no code fences, no comments,
   no explanation, no trailing semicolon. One statement only.
3. Only SELECT is allowed. Never produce DROP, DELETE, UPDATE, INSERT, ALTER,
   TRUNCATE, or any other DDL/DML.
4. Only reference these tables/views: v_completed_sales, sales_transactions,
   data_quality_audit. Only use the columns listed above.
5. Give every calculated column a short, clear alias (for example total_revenue,
   order_count, discounted_orders_pct). Use ROUND(..., 2) for percentages.
6. If the question is not about this sales data (weather, geography, sports,
   general knowledge), respond with exactly: OUT_OF_SCOPE

EXAMPLES
--------
Q: What is the total revenue?
A: SELECT SUM(net_revenue) AS total_net_revenue FROM v_completed_sales

Q: Which product generated the highest revenue?
A: SELECT product, SUM(net_revenue) AS total_revenue FROM v_completed_sales GROUP BY product ORDER BY total_revenue DESC

Q: What percentage of completed orders had a discount?
A: SELECT ROUND(100.0 * SUM(CASE WHEN discount_amount > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS discounted_orders_pct FROM v_completed_sales
"""

_TIMEOUT_SECONDS = 30   # newer Gemini models can take well over 15 s to answer


# --- Client -------------------------------------------------------------------

class LLMClient:
    """
    Thin wrapper around the google-genai SDK.
    Converts a natural language question into a single SQL SELECT.
    """

    def __init__(self):
        if not LLM_ENABLED:
            raise LLMDisabledError("LLM is disabled (LLM_ENABLED=false).")
        if not GOOGLE_API_KEY:
            raise LLMDisabledError("GOOGLE_API_KEY is not set — LLM unavailable.")
        # The key is read from config and never logged. The SDK timeout is in milliseconds.
        self._client = genai.Client(
            api_key=GOOGLE_API_KEY,
            http_options=genai_types.HttpOptions(timeout=_TIMEOUT_SECONDS * 1000),
        )
        self._model = LLM_MODEL

    def generate_sql(self, question: str, schema_context: str = "") -> str:
        """
        Ask the LLM to turn `question` into a single SQL SELECT.

        Parameters
        ----------
        question       : the user's natural language question
        schema_context : on a retry, the error from the previous attempt (the schema
                         itself always lives in the system prompt)

        Returns
        -------
        One SQL statement, or the text OUT_OF_SCOPE.

        Raises
        ------
        LLMGenerationError on any API / network / timeout error or an empty reply.
        """
        user_prompt = f"Generate a SQL query for this question: {question}"
        if schema_context:
            user_prompt += f"\n\nNote from previous attempt: {schema_context}"

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    temperature=0.0,            # as repeatable as possible
                    # Generous limit: newer Gemini models spend part of this budget on
                    # internal reasoning, so a small value can cut the answer short.
                    max_output_tokens=2048,
                ),
            )
            raw = response.text or ""
        except Exception as exc:
            raise LLMGenerationError(f"Gemini API call failed: {exc}") from exc

        if not raw.strip():
            raise LLMGenerationError("Gemini returned an empty reply.")

        sql = extract_sql(raw)
        logger.debug("LLM generated SQL: %s", sql)
        return sql