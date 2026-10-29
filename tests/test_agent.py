import pytest
from src.agent import SalesBIAgent

@pytest.fixture(scope="module")
def agent():
    return SalesBIAgent()

def test_agent_total_revenue(agent):
    """Test agent processing natural language question for total revenue."""
    res = agent.process_question("What is the total revenue?")
    assert res["status"] == "success"
    assert "1,445,200.00" in res["answer"]
    assert res["sql_query"] != ""
    assert len(res["reasoning_trace"]) > 0

def test_agent_top_product(agent):
    """Test agent processing natural language question for top product."""
    res = agent.process_question("Which product generated the highest revenue?")
    assert res["status"] == "success"
    assert "Monitor" in res["answer"]

def test_agent_monthly_trend(agent):
    """Test agent processing monthly trend question."""
    res = agent.process_question("What is the monthly revenue trend?")
    assert res["status"] == "success"
    assert res["chart_type"] == "line"

def test_agent_regional_sales(agent):
    """Test agent processing regional sales question."""
    res = agent.process_question("Which region generated the highest sales?")
    assert res["status"] == "success"
    assert "South" in res["answer"]

def test_agent_month_over_month(agent):
    """Test agent comparing two specific months."""
    res = agent.process_question("How did revenue change between January and February?")
    assert res["status"] == "success"
    assert "24,350.00" in res["answer"]

def test_agent_empty_question(agent):
    """Test edge case: empty user question."""
    res = agent.process_question("   ")
    assert res["status"] == "invalid_request"

def test_agent_out_of_domain_guardrail(agent):
    """Test guardrail against unrelated non-BI queries."""
    res = agent.process_question("What is the capital of France and what is the weather today?")
    assert res["status"] == "out_of_domain"
    assert "specialized in" in res["answer"].lower()
