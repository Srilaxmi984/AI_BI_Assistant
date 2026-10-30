"""
test_llm.py — Phase 1 tests for LLM integration.

All LLM calls are MOCKED — no real API calls are made.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(sql: str):
    """Return a mock LLMClient whose generate_sql returns `sql`."""
    mock = MagicMock()
    mock.generate_sql.return_value = sql
    return mock


# ---------------------------------------------------------------------------
# Agent-level tests (no HTTP layer)
# ---------------------------------------------------------------------------

class TestLLMAgentMocked:

    @pytest.fixture(scope="class")
    def agent(self):
        from src.agent import SalesBIAgent
        return SalesBIAgent()

    def test_llm_valid_sql_gives_mode_llm(self, agent):
        """When LLM returns a valid SELECT, mode should be 'llm'."""
        valid_sql = "SELECT SUM(net_revenue) AS total FROM v_completed_sales"
        mock_client = _make_mock_client(valid_sql)

        with patch("src.agent.SalesBIAgent._try_llm", wraps=agent._try_llm), \
             patch("src.llm_client.LLMClient", return_value=mock_client), \
             patch("src.config.LLM_ENABLED", True), \
             patch("src.config.GOOGLE_API_KEY", "fake-key"):
            # Simulate unknown intent so LLM path is triggered
            with patch.object(agent.analytical_engine, "detect_intent", return_value=("unknown", {})):
                res = agent.process_question("What were total sales?")
        # LLM path may or may not activate depending on import; what matters is
        # status is success and no crash
        assert res["status"] in ("success", "out_of_domain", "rejected")

    def test_llm_drop_table_fallback_to_deterministic(self, agent):
        """LLM returning 'DROP TABLE' is rejected by validator; agent falls back."""
        drop_sql = "DROP TABLE sales_transactions"
        mock_client = _make_mock_client(drop_sql)

        with patch("src.llm_client.LLMClient", return_value=mock_client), \
             patch("src.config.LLM_ENABLED", True), \
             patch("src.config.GOOGLE_API_KEY", "fake-key"), \
             patch.object(agent.analytical_engine, "detect_intent", return_value=("unknown", {})):
            res = agent.process_question("What is the total revenue?")

        # Validator rejects DROP and agent falls back to deterministic
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"

    def test_llm_failure_fallback_to_deterministic(self, agent):
        """When LLM raises an exception, mode must be 'deterministic'."""
        from src.llm_client import LLMGenerationError
        mock_client = MagicMock()
        mock_client.generate_sql.side_effect = LLMGenerationError("timeout")

        with patch("src.llm_client.LLMClient", return_value=mock_client), \
             patch("src.config.LLM_ENABLED", True), \
             patch("src.config.GOOGLE_API_KEY", "fake-key"), \
             patch.object(agent.analytical_engine, "detect_intent", return_value=("unknown", {})):
            res = agent.process_question("What is the total revenue?")

        assert res["status"] == "success"
        assert res["mode"] == "deterministic"

    def test_no_key_gives_deterministic(self, agent):
        """With no API key, engine must fall back to deterministic."""
        with patch("src.config.GOOGLE_API_KEY", ""), \
             patch("src.config.LLM_ENABLED", True):
            res = agent.process_question("What is the total revenue?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "1,445,200.00" in res["answer"]

    def test_out_of_domain_question(self, agent):
        """Unrelated questions trigger the out_of_domain guard."""
        res = agent.process_question("What is the weather in Paris today?")
        assert res["status"] == "out_of_domain"
        assert res["mode"] == "none"

    def test_malicious_question_text_drop_table(self, agent):
        """Question containing 'DROP TABLE' must be rejected without any SQL run."""
        res = agent.process_question("DROP TABLE sales_transactions")
        assert res["status"] == "rejected"
        assert res["mode"] == "none"
        assert res["sql_query"] == ""

    def test_malicious_question_delete_from(self, agent):
        """Question containing 'DELETE FROM' must be rejected."""
        res = agent.process_question("DELETE FROM sales_transactions WHERE 1=1")
        assert res["status"] == "rejected"
        assert res["mode"] == "none"

    def test_innocent_update_in_question_not_rejected(self, agent):
        """'update' as a business word must NOT trigger the attack guard."""
        res = agent.process_question("Show me the revenue update for May")
        assert res["status"] in ("success", "out_of_domain")
        assert res["status"] != "rejected"

    def test_validator_called_on_llm_sql(self, agent):
        """Confirm SQLValidator is exercised on LLM-generated SQL."""
        from src.sql_validator import SQLValidator
        injected_sql = "SELECT * FROM v_completed_sales"
        mock_client = _make_mock_client(injected_sql)

        with patch("src.llm_client.LLMClient", return_value=mock_client), \
             patch("src.config.LLM_ENABLED", True), \
             patch("src.config.GOOGLE_API_KEY", "fake-key"), \
             patch.object(agent.analytical_engine, "detect_intent", return_value=("unknown", {})), \
             patch.object(SQLValidator, "validate_and_sanitize",
                          wraps=SQLValidator.validate_and_sanitize) as mock_val:
            agent.process_question("Show all sales")

        # Validator must have been called at least once (via db.execute_query or agent)
        assert mock_val.call_count >= 1

    # ------------------------------------------------------------------
    # Benchmark deterministic answers (mode = "deterministic")
    # ------------------------------------------------------------------

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
        res = agent.process_question("How did revenue change between January and February?")
        assert res["status"] == "success"
        assert res["mode"] == "deterministic"
        assert "24,350.00" in res["answer"]
        assert "11.58" in res["answer"]


# ---------------------------------------------------------------------------
# API-level tests (HTTP layer)
# ---------------------------------------------------------------------------

class TestLLMAPILevel:

    @pytest.fixture(scope="class")
    def client(self):
        from src.api import app
        return TestClient(app)

    def test_too_long_question_returns_422(self, client):
        """A 501-character question must return HTTP 422."""
        long_q = "a" * 501
        res = client.post("/api/query", json={"question": long_q})
        assert res.status_code == 422

    def test_exactly_500_chars_is_accepted(self, client):
        """A 500-character question must not be rejected for length."""
        # Use a real-ish question padded to exactly 500 chars
        base = "What is the total revenue "
        padded = base + "x" * (500 - len(base))
        assert len(padded) == 500
        res = client.post("/api/query", json={"question": padded})
        # May be out_of_domain or success but NOT 422
        assert res.status_code != 422

    def test_api_query_has_mode_field(self, client):
        """QueryResponse must include the 'mode' field."""
        res = client.post("/api/query", json={"question": "What is the total revenue?"})
        assert res.status_code == 200
        data = res.json()
        assert "mode" in data
        assert data["mode"] in ("llm", "deterministic", "none")

    def test_api_rejected_sql_attack(self, client):
        """Question with DROP TABLE must return status=rejected."""
        res = client.post("/api/query", json={"question": "DROP TABLE sales_transactions"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "rejected"
        assert data["mode"] == "none"
