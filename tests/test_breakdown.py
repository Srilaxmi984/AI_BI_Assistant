import pytest
from src.agent import SalesBIAgent
from src.analytical_engine import AnalyticalEngine
from src.database import DatabaseManager


@pytest.fixture(scope="module")
def engine():
    return AnalyticalEngine(DatabaseManager())


def run(engine, question):
    """Route a question and run it through the breakdown engine."""
    intent, params = engine.detect_intent(question)
    assert intent == "breakdown", f"{question!r} was routed to {intent!r}"
    return engine.breakdown.run(params["spec"])


# ---- the five benchmark phrasings must still use their original intents ----

@pytest.mark.parametrize("question, expected", [
    ("What is the total revenue?", "total_revenue"),
    ("Which product generated the highest revenue?", "highest_revenue_product"),
    ("What is the monthly revenue trend?", "monthly_revenue_trend"),
    ("Which region generated the highest sales?", "highest_sales_region"),
    ("How did revenue change between January and February?", "revenue_change_between_months"),
])
def test_benchmark_questions_keep_their_intent(engine, question, expected):
    assert engine.detect_intent(question)[0] == expected


# ---- valid questions with exact, known figures ----

def test_revenue_in_a_month(engine):
    res = run(engine, "What was the revenue in January?")
    assert "$210,250.00" in res["answer"]


def test_revenue_of_one_product(engine):
    res = run(engine, "What is the revenue of Monitor?")
    assert "$473,000.00" in res["answer"]


def test_top_two_products(engine):
    res = run(engine, "Show the top 2 products by revenue")
    rows = res["table_data"]
    assert [r["product"] for r in rows] == ["Monitor", "Desk"]
    assert rows[0]["total_revenue"] == 473000.0
    assert rows[1]["total_revenue"] == 222500.0


def test_top_three_regions(engine):
    res = run(engine, "Top 3 regions by revenue")
    assert [r["region"] for r in res["table_data"]] == ["South", "North", "East"]


def test_lowest_region(engine):
    res = run(engine, "Which region has the lowest revenue?")
    assert res["table_data"][0]["region"] == "West"
    assert res["table_data"][0]["total_revenue"] == 296850.0
    assert "lowest" in res["answer"]


# ---- consistency checks that need no hand-typed numbers ----

def test_units_per_product_add_up_to_total_units(engine):
    res = run(engine, "How many units were sold per product?")
    total_units = engine.get_total_revenue()["supporting_figures"]["total_units_sold"]
    assert sum(r["total_units"] for r in res["table_data"]) == total_units


def test_orders_per_region_add_up_to_all_completed_orders(engine):
    res = run(engine, "Number of orders per region")
    assert sum(r["order_count"] for r in res["table_data"]) == 50


def test_regions_in_january_add_up_to_january_revenue(engine):
    res = run(engine, "Show revenue by region in January")
    assert sum(r["total_revenue"] for r in res["table_data"]) == pytest.approx(210250.0)


# ---- invalid and edge cases ----

def test_month_without_data_gets_a_clear_message(engine):
    res = run(engine, "What was the revenue in July?")
    assert "no sales data" in res["answer"].lower()
    assert res["table_data"] == []


def test_ordinary_words_are_not_read_as_months(engine):
    # "market" contains "mar" and "compare" is a change word: neither may trigger a month comparison
    assert engine.detect_intent("compare product sales in the market")[0] == "unknown"


def test_two_groupings_are_left_to_the_llm(engine):
    assert engine.detect_intent("Show revenue by product and region")[0] == "unknown"


def test_question_text_never_reaches_the_sql(engine):
    intent, params = engine.detect_intent("revenue for South' OR '1'='1")
    assert intent == "breakdown"
    sql = engine.breakdown.build_sql(params["spec"])
    assert "1'='1" not in sql
    assert "IN ('South')" in sql


# ---- through the agent (guards, validator choke point, response shape) ----

def test_agent_answers_a_filtered_question_without_the_llm():
    res = SalesBIAgent().process_question("What was the revenue in January?")
    assert res["status"] == "success"
    assert res["mode"] == "deterministic"
    assert "$210,250.00" in res["answer"]
    assert res["sql_query"].startswith("SELECT")


def test_agent_reports_missing_month():
    res = SalesBIAgent().process_question("Revenue in July")
    assert "no sales data" in res["answer"].lower()