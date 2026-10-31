"""
test_llm.py — tests for LLM integration and guardrails.

All LLM API calls are MOCKED — no real network traffic is made.
(tests/conftest.py also makes the real Gemini client fail instantly, so a test that
forgets to mock the model cannot reach the network.)
"""

import pytest
from unittest.mock import patch, MagicMock, call
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PCT_SQL = (
    "SELECT ROUND(100.0 * SUM(CASE WHEN discount_amount > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) "
    "AS discounted_orders_pct FROM v_completed_sales"
)


def _make_mock_client(sql: str):
    mock = MagicMock()
    mock.generate_sql.return_value = sql
    return mock


# ---------------------------------------------------------------------------
# Agent-level tests
# ---------------------------------------------------------------------------

class TestLLMAgentMocked:

    @pytest.fixture(scope="class")
    def agent(self):
        from src.agent import SalesBIAgent
        return SalesBIAgent()

    # -- The LLM path really works ------------------------------------------

    def test_valid_llm_sql_gives_mode_llm(self, agent):
        """A valid SELECT from the model is validated, run, and answered with mode=llm."""
        mock_client = _make_mock_client(PCT_SQL)
        with patch("src.llm_client.LLMClient", return_value=mock_client):
            res = agent.process_question("What percentage of completed orders had a discount?")
        assert res["status"] == "success"
        assert res["mode"] == "llm"
        assert res["sql_query"].upper().startswith("SELECT")
        assert "8.00%" in res["answer"]          # 4 of 50 completed orders had a discount
        mock_client.generate_sql.assert_called_once()

    def test_numbers_come_from_the_rows_not_from_the_model(self, agent):
        """Whatever text the model adds, the answer shows the database result."""
        mock_client = _make_mock_client(PCT_SQL)
        with patch("src.llm_client.LLMClient", return_value=mock_client):
            res = agent.process_question("What percentage of completed orders had a discount?")
        assert res["table_data"][0]["discounted_orders_pct"] == 8.0

    # -- Unknown question when the LLM is unavailable -------------------------

    def test_unknown_question_no_llm_returns_cant_answer(self, agent):
        """With the key missing and no exploratory keyword: 'can't answer', mode=none."""
        with patch("src.llm_client.GOOGLE_API_KEY", ""):
            res = agent.process_question("What is the meaning of life?")
        assert res["status"] == "out_of_domain"
        assert res["mode"] == "none"
        assert "can't answer" in res["answer"].lower()
        # the trace says why Gemini was not used
        assert any("no api key" in s["detail"].lower() for s in res["reasoning_trace"])

    def test_percentage_question_without_gemini_is_not_answered_wrongly(self, agent):
        """The 'discount' keyword branch would return total discounts, which is a different figure."""
        with patch("src.llm_client.GOOGLE_API_KEY", ""):
            res = agent.process_question("What percentage of completed orders had a discount?")
        assert res["mode"] == "none"
        assert "can't answer" in res["answer"].lower()
        assert "4,500" not in res["answer"]

    # -- OUT_OF_SCOPE sentinel ------------------------------------------------

    def test_llm_out_of_scope_sentinel_maps_to_out_of_domain(self, agent):
        """When LLM returns OUT_OF_SCOPE, map to status=out_of_domain, mode=none."""
        mock_client = _make_mock_client("OUT_OF_SCOPE")
        with patch("src.llm_client.LLMClient", return_value=mock_client), \
             patch.object(agent.analytical_engine, "detect_intent",
                          return_value=("unknown", {})):
            res = agent.process_question("Who won the cricket World Cup?")
        assert res["status"] == "out_of_domain"
        assert res["mode"] == "none"
        assert res["sql_query"] == ""

    # -- No raw exception text to users --------------------------------------

    def test_deterministic_error_returns_generic_message(self, agent):
        """Engine crash must not expose raw exception text to the user."""
        with patch.object(agent.analytical_engine, "get_total_revenue",
                          side_effect=RuntimeError("internal db error xyz")):
            with patch.object(agent.analytical_engine, "detect_intent",
                              return_value=("total_revenue", {})):
                res = agent.process_question("What is the total revenue?")
        assert res["status"] == "error"
        assert "internal db error xyz" not in res["answer"]
        assert "internal error" in res["answer"].lower()

    def test_llm_failure_reason_is_shown_without_raw_error_text(self, agent):
        """The trace explains a Gemini failure in plain words and never repeats the raw error."""
        mock_client = MagicMock()
        mock_client.generate_sql.side_effect = Exception("403 PERMISSION_DENIED secret-details")
        with patch("src.llm_client.LLMClient", return_value=mock_client):
            res = agent.process_question("What is the average order value?")
        trace = " ".join(s["detail"] for s in res["reasoning_trace"])
        assert "permission or billing" in trace.lower()
        assert "secret-details" not in trace

    # -- No class-level _last_llm_error attribute ------------------------------

    def test_no_class_level_last_llm_error(self):
        """SalesBIAgent must not have a _last_llm_error class attribute."""
        from src.agent import SalesBIAgent
        assert not hasattr(SalesBIAgent, "_last_llm_error"), \
            "_last_llm_error must be a local variable, not a class attribute"

    # -- Validator is used for model-written SQL --------------------------------

    def test_validator_instance_used_in_try_llm(self, agent):
        """LLM SQL must be validated through self.validator (the instance)."""
        valid_sql = "SELECT SUM(net_revenue) AS total FROM v_completed_sales"
        mock_client = _make_mock_client(valid_sql)

        with patch("src.llm_client.LLMClient", return_value=mock_client), \
             patch.object(agent.analytical_engine, "detect_intent",
                          return_value=("unknown", {})), \
             patch.object(agent.validator, "validate_and_sanitize",
                          wraps=agent.validator.validate_and_sanitize) as mock_val:
            agent.process_question("What were total sales?")

        assert mock_val.call_count >= 1, "self.validator.validate_and_sanitize was not called"

    # -- All 5 deterministic queries pass through SQLValidator -------------------

    def test_total_revenue_goes_through_validator(self, agent):
        """get_total_revenue SQL must pass through database.execute_query/validator."""
        from src.sql_validator import SQLValidator
        with patch.object(SQLValidator, "validate_and_sanitize",
                          wraps=SQLValidator.validate_and_sanitize) as mock_val:
            res = agent.process_question("What is the total revenue?")
        assert res["status"] == "success"
        assert mock_val.call_count >= 1

    def test_top_product_goes_through_validator(self, agent):
        """get_highest_revenue_product SQL must pass through validator."""
        from src.sql_validator import SQLValidator
        with patch.object(SQLValidator, "validate_and_sanitize",
                          wraps=SQLValidator.validate_and_sanitize) as mock_val:
            res = agent.process_question("Which product generated the highest revenue?")
        assert res["status"] == "success"
        assert mock_val.call_count >= 1

    def test_monthly_trend_goes_through_validator(self, agent):
        """get_monthly_revenue_trend SQL must pass through validator."""
        from src.sql_validator import SQLValidator
        with patch.object(SQLValidator, "validate_and_sanitize",
                          wraps=SQLValidator.validate_and_sanitize) as mock_val:
            res = agent.process_question("What is the monthly revenue trend?")
        assert res["status"] == "success"
        assert mock_val.call_count >= 1

    def test_top_region_goes_through_validator(self, agent):
        """get_highest_sales_region SQL must pass through validator."""
        from src.sql_validator import SQLValidator
        with patch.object(SQLValidator, "validate_and_sanitize",
                          wraps=SQLValidator.validate_and_sanitize) as mock_val:
            res = agent.process_question("Which region generated the highest sales?")
        assert res["status"] == "success"
        assert mock_val.call_count >= 1

    def test_revenue_change_goes_through_validator(self, agent):
        """get_revenue_change_between_months SQL must pass through validator."""
        from src.sql_validator import SQLValidator
        with patch.object(SQLValidator, "validate_and_sanitize",
                          wraps=SQLValidator.validate_and_sanitize) as mock_val:
            res = agent.process_question(
                "How did revenue change between January and February?")
        assert res["status"] == "success"
        assert mock_val.call_count >= 1

    # -- Destructive or broken model output ---------------------------------------
    # "What is the average order value?" is not one of the fixed intents, so it
    # really goes to the model, and the exploratory branch answers if the model fails.

    def test_llm_drop_table_is_rejected_retried_then_falls_back(self, agent):
        """DROP TABLE from the model is rejected twice; the verified branch answers instead."""
        mock_client = _make_mock_client("DROP TABLE sales_transactions")
        with patch("src.llm_client.LLMClient", return_value=mock_client):
            res = agent.process_question("What is the average order value?")
        assert mock_client.generate_sql.call_count == 2        # first try + one retry
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "average order value" in res["answer"].lower()

    def test_stacked_statement_from_llm_is_rejected_and_data_survives(self, agent):
        """'SELECT ...; DROP TABLE ...' must never run, and the table must still exist after."""
        mock_client = _make_mock_client("SELECT 1; DROP TABLE sales_transactions")
        with patch("src.llm_client.LLMClient", return_value=mock_client):
            res = agent.process_question("What is the average order value?")
        assert res["mode"] == "deterministic"
        after = agent.process_question("What is the total revenue?")
        assert "1,445,200.00" in after["answer"]

    def test_llm_failure_falls_back_without_retrying(self, agent):
        """A Gemini error (timeout, quota, ...) falls back at once; retrying would not help."""
        from src.llm_client import LLMGenerationError
        mock_client = MagicMock()
        mock_client.generate_sql.side_effect = LLMGenerationError("timeout")
        with patch("src.llm_client.LLMClient", return_value=mock_client):
            res = agent.process_question("What is the average order value?")
        assert mock_client.generate_sql.call_count == 1
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"

    def test_no_key_gives_deterministic(self, agent):
        """No API key → the benchmark answer is still correct and deterministic."""
        with patch("src.llm_client.GOOGLE_API_KEY", ""):
            res = agent.process_question("What is the total revenue?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "1,445,200.00" in res["answer"]

    # -- Question text guards ------------------------------------------------------

    def test_malicious_question_drop_table(self, agent):
        """DROP TABLE in question text → rejected, mode=none, no SQL run."""
        res = agent.process_question("DROP TABLE sales_transactions")
        assert res["status"] == "rejected"
        assert res["mode"] == "none"
        assert res["sql_query"] == ""

    def test_malicious_question_delete_from(self, agent):
        """DELETE FROM in question text → rejected."""
        res = agent.process_question("DELETE FROM sales_transactions WHERE 1=1")
        assert res["status"] == "rejected"
        assert res["mode"] == "none"

    def test_innocent_update_not_rejected(self, agent):
        """'update' as a business word must NOT trigger the attack guard."""
        res = agent.process_question("Show me the revenue update for May")
        assert res["status"] not in ("rejected",)

    def test_out_of_domain_weather(self, agent):
        """Weather question → out_of_domain, mode=none."""
        res = agent.process_question("What is the weather in Paris today?")
        assert res["status"] == "out_of_domain"
        assert res["mode"] == "none"

    # -- Benchmark deterministic answers --------------------------------------------

    def test_benchmark_total_revenue(self, agent):
        res = agent.process_question("What is the total revenue?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "1,445,200.00" in res["answer"]

    def test_benchmark_top_product(self, agent):
        res = agent.process_question("Which product generated the highest revenue?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "Monitor" in res["answer"]
        assert "473,000.00" in res["answer"]

    def test_benchmark_monthly_trend(self, agent):
        res = agent.process_question("What is the monthly revenue trend?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert res["chart_type"] == "line"

    def test_benchmark_top_region(self, agent):
        res = agent.process_question("Which region generated the highest sales?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "South" in res["answer"]
        assert "411,200.00" in res["answer"]

    def test_benchmark_jan_to_feb(self, agent):
        res = agent.process_question(
            "How did revenue change between January and February?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "24,350.00" in res["answer"]
        assert "11.58" in res["answer"]


# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------

class TestLLMAPILevel:

    @pytest.fixture(scope="class")
    def client(self):
        from src.api import app
        return TestClient(app)

    def test_too_long_question_returns_422(self, client):
        """501-character question → HTTP 422."""
        res = client.post("/api/query", json={"question": "a" * 501})
        assert res.status_code == 422

    def test_exactly_500_chars_is_accepted(self, client):
        """500-char question must not be rejected for length."""
        base = "What is the total revenue "
        padded = base + "x" * (500 - len(base))
        assert len(padded) == 500
        res = client.post("/api/query", json={"question": padded})
        assert res.status_code != 422

    def test_api_query_has_mode_field(self, client):
        """QueryResponse must include the 'mode' field."""
        res = client.post("/api/query", json={"question": "What is the total revenue?"})
        assert res.status_code == 200
        data = res.json()
        assert "mode" in data
        assert data["mode"] in ("llm", "deterministic", "none")

    def test_api_rejected_sql_attack(self, client):
        """DROP TABLE in question → status=rejected, mode=none."""
        res = client.post("/api/query",
                          json={"question": "DROP TABLE sales_transactions"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "rejected"
        assert data["mode"] == "none"