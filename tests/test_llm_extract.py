from src.llm_client import extract_sql


def test_extracts_sql_from_fenced_reply_with_commentary():
    reply = "```sql\nSELECT COUNT(*) AS n FROM v_completed_sales;\n```\n` works in SQLite."
    assert extract_sql(reply) == "SELECT COUNT(*) AS n FROM v_completed_sales"


def test_plain_sql_is_unchanged():
    assert extract_sql("SELECT 1") == "SELECT 1"


def test_out_of_scope_marker_is_recognised():
    assert extract_sql("`OUT_OF_SCOPE`") == "OUT_OF_SCOPE"


def test_destructive_sql_is_not_hidden_from_the_validator():
    assert extract_sql("```sql\nDROP TABLE sales_transactions;\n```").startswith("DROP TABLE")


def test_stacked_statements_reach_the_validator_unchanged():
    reply = "SELECT 1; DROP TABLE sales_transactions;"
    assert "DROP TABLE" in extract_sql(reply)
