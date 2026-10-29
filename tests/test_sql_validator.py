import pytest
from src.sql_validator import SQLValidator

def test_valid_select_query():
    """Verify that legitimate SELECT queries pass validation."""
    query = "SELECT product, SUM(net_revenue) FROM v_completed_sales GROUP BY product"
    is_valid, sanitized, err = SQLValidator.validate_and_sanitize(query)
    assert is_valid is True
    assert err is None
    assert "LIMIT" in sanitized

def test_block_drop_table():
    """Verify that DROP TABLE statements are blocked."""
    query = "DROP TABLE sales_transactions;"
    is_valid, sanitized, err = SQLValidator.validate_and_sanitize(query)
    assert is_valid is False
    assert "not allowed" in err or "forbidden" in err.lower()

def test_block_delete_statement():
    """Verify that DELETE statements are blocked."""
    query = "DELETE FROM sales_transactions WHERE region = 'North';"
    is_valid, sanitized, err = SQLValidator.validate_and_sanitize(query)
    assert is_valid is False
    assert "forbidden" in err.lower() or "not allowed" in err.lower()

def test_block_update_statement():
    """Verify that UPDATE statements are blocked."""
    query = "UPDATE sales_transactions SET net_revenue = 999999;"
    is_valid, sanitized, err = SQLValidator.validate_and_sanitize(query)
    assert is_valid is False

def test_block_piggyback_multiple_statements():
    """Verify that stacked SQL injection statements (semicolon delimited) are blocked."""
    query = "SELECT * FROM v_completed_sales; DROP TABLE sales_transactions;"
    is_valid, sanitized, err = SQLValidator.validate_and_sanitize(query)
    assert is_valid is False
    assert "Multiple SQL statements detected" in err

def test_block_unauthorized_table():
    """Verify that querying arbitrary system or external tables is blocked."""
    query = "SELECT * FROM sqlite_master;"
    is_valid, sanitized, err = SQLValidator.validate_and_sanitize(query)
    assert is_valid is False
    assert "not in the allowed schema" in err
