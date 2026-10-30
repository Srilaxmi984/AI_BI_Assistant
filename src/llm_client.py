"""
llm_client.py — Gemini text-to-SQL client using the google-genai SDK.

Usage:
    client = LLMClient()
    sql = client.generate_sql(question, schema_context)  # returns a raw SELECT string

Raises:
    LLMDisabledError   – when LLM_ENABLED=false or GOOGLE_API_KEY is empty
    LLMGenerationError – on API / network / timeout failure
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
    """Raised when the Gemini API call fails or times out."""


# --- System prompt -------------------------------------------------------------

_SYSTEM_PROMPT = """You are a SQL generation assistant for a SQLite sales database.

SCHEMA
------
Table: sales_transactions
  transaction_id TEXT, order_date TEXT (YYYY-MM-DD), customer_id TEXT,
  product TEXT, category TEXT, region TEXT, sales_channel TEXT,
  quantity INTEGER, unit_price REAL, gross_revenue REAL,
  discount_amount REAL, net_revenue REAL, status TEXT, is_imputed INTEGER,
  year_month TEXT (YYYY-MM)

View:  v_completed_sales   — same columns as sales_transactions, pre-filtered
       WHERE status = 'Completed'. Use this for ALL revenue calculations.

Table: data_quality_audit
  id INTEGER, transaction_id TEXT, issue_type TEXT, description TEXT,
  action_taken TEXT, timestamp TEXT

RULES
-----
1. Revenue questions MUST use v_completed_sales and the net_revenue column.
   NEVER query sales_transactions for revenue figures.
2. Return ONLY one SQL SELECT statement — no explanation, no markdown fences,
   no trailing semicolon.
3. Only SELECT is allowed. Never produce DROP, DELETE, UPDATE, INSERT,
   ALTER, TRUNCATE, or any DDL/DML.
4. Only reference these tables/views: v_completed_sales, sales_transactions,
   data_quality_audit.

EXAMPLES
--------
Q: What is the total revenue?
A: SELECT SUM(net_revenue) AS total_net_revenue FROM v_completed_sales

Q: Which product generated the highest revenue?
A: SELECT product, SUM(net_revenue) AS total_revenue
   FROM v_completed_sales
   GROUP BY product
   ORDER BY total_revenue DESC
"""

_TIMEOUT_SECONDS = 15


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
        # Initialise the client; key is read from config, never logged
        self._client = genai.Client(api_key=GOOGLE_API_KEY)
        self._model = LLM_MODEL

    def generate_sql(self, question: str, schema_context: str = "") -> str:
        """
        Ask the LLM to turn `question` into a single SQL SELECT.

        Parameters
        ----------
        question       : the user's natural language question
        schema_context : optional extra context (unused; schema is in system prompt)

        Returns
        -------
        A raw SQL SELECT string (markdown fences stripped).

        Raises
        ------
        LLMGenerationError on any API / network / timeout error.
        """
        user_prompt = f"Generate a SQL query for this question: {question}"

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    temperature=0.0,          # deterministic output
                    max_output_tokens=512,
                    timeout=_TIMEOUT_SECONDS,
                ),
            )
            raw = response.text or ""
        except Exception as exc:
            raise LLMGenerationError(f"Gemini API call failed: {exc}") from exc

        sql = _strip_fences(raw)
        logger.debug("LLM generated SQL: %s", sql)
        return sql


# --- Helpers ------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove ```sql ... ``` or ``` ... ``` markdown fences if present."""
    text = text.strip()
    # Remove opening fence (```sql or ```)
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    # Remove closing fence
    text = re.sub(r"\s*```$", "", text)
    # Strip trailing semicolon
    return text.strip().rstrip(";").strip()
