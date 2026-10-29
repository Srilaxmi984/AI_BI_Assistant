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

def test_agent_category_breakdown(agent):
    """Test agent answering product category sales query."""
    res = agent.process_question("Which category has the highest sales?")
    assert res["status"] == "success"
    assert "Accessories" in res["answer"]
    assert res["chart_type"] == "bar"

def test_agent_channel_breakdown(agent):
    """Test agent answering sales channel breakdown query."""
    res = agent.process_question("Show me performance by sales channel")
    assert res["status"] == "success"
    assert "Online" in res["answer"]
    assert "Retail" in res["answer"]

def test_agent_discounts_query(agent):
    """Test agent calculating total discounts granted."""
    res = agent.process_question("What were the discounts given?")
    assert res["status"] == "success"
    assert "4,500.00" in res["answer"]

def test_agent_average_order_value(agent):
    """Test agent calculating average order value."""
    res = agent.process_question("What is the average order value?")
    assert res["status"] == "success"
    assert "28,904.00" in res["answer"]

def test_agent_dynamic_month_comparison(agent):
    """Test agent dynamically parsing and comparing April and May."""
    res = agent.process_question("How did revenue change between April and May?")
    assert res["status"] == "success"
    assert "77,800.00" in res["answer"]
    assert "32.32%" in res["answer"]

