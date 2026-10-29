import pytest
from src.analytical_engine import AnalyticalEngine
from src.database import DatabaseManager

@pytest.fixture(scope="module")
def engine():
    return AnalyticalEngine(DatabaseManager())

def test_q1_total_revenue(engine):
    """Q1: What is the total revenue?"""
    res = engine.get_total_revenue()
    assert res["intent"] == "total_revenue"
    figures = res["supporting_figures"]
    assert figures["total_net_revenue"] == 1445200.0
    assert figures["gross_revenue"] == 1449700.0
    assert figures["total_discounts"] == 4500.0
    assert figures["transaction_count"] == 50
    assert "$1,445,200.00" in res["answer"]

def test_q2_highest_revenue_product(engine):
    """Q2: Which product generated the highest revenue?"""
    res = engine.get_highest_revenue_product()
    assert res["intent"] == "product_revenue"
    figures = res["supporting_figures"]
    assert figures["top_product"] == "Monitor"
    assert figures["top_product_revenue"] == 473000.0
    assert "Monitor" in res["answer"]
    assert res["chart_type"] == "bar"

def test_q3_monthly_revenue_trend(engine):
    """Q3: What is the monthly revenue trend?"""
    res = engine.get_monthly_revenue_trend()
    assert res["intent"] == "monthly_revenue_trend"
    figures = res["supporting_figures"]
    assert figures["peak_month"] == "2026-05"
    assert figures["peak_revenue"] == 318500.0
    assert len(figures["trend"]) == 6
    assert res["chart_type"] == "line"

def test_q4_highest_sales_region(engine):
    """Q4: Which region generated the highest sales?"""
    res = engine.get_highest_sales_region()
    assert res["intent"] == "region_sales"
    figures = res["supporting_figures"]
    assert figures["top_region"] == "South"
    assert figures["top_region_revenue"] == 411200.0
    assert "South" in res["answer"]

def test_q5_revenue_change_between_months(engine):
    """Q5: How did revenue change between two months?"""
    res = engine.get_revenue_change_between_months("2026-01", "2026-02")
    assert res["intent"] == "revenue_change_between_months"
    figures = res["supporting_figures"]
    assert figures["revenue_1"] == 210250.0
    assert figures["revenue_2"] == 234600.0
    assert figures["absolute_change"] == 24350.0
    assert figures["percent_change"] == 11.58
    assert figures["direction"] == "increased"
    assert "increased by $24,350.00" in res["answer"]
