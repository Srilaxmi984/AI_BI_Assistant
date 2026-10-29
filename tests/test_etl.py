import pytest
from src.etl import run_etl
from src.database import DatabaseManager
from src.config import PROCESSED_DB_PATH

def test_etl_execution():
    """Verify that ETL processes all 51 rows and populates SQLite tables."""
    summary = run_etl()
    assert summary["status"] == "success"
    assert summary["total_records_processed"] == 51
    assert summary["completed_sales_count"] == 50
    assert summary["returned_sales_count"] == 1
    assert summary["imputed_records_count"] == 1
    assert summary["quality_issues_detected"] >= 3

def test_missing_price_imputation():
    """Edge Case: Verify that TXN0051 (missing unit price) was properly imputed."""
    db = DatabaseManager()
    rows = db.execute_query("SELECT * FROM sales_transactions WHERE transaction_id = 'TXN0051';")
    assert len(rows) == 1
    row = rows[0]
    assert row["product"] == "Laptop Stand"
    assert row["unit_price"] == 1200.0
    assert row["is_imputed"] == 1
    assert row["data_quality_flag"] == "IMPUTED_UNIT_PRICE"
    assert row["gross_revenue"] == 5 * 1200.0

def test_returned_item_quarantine():
    """Edge Case: Verify that TXN0033 (Status: Returned) is excluded from completed view."""
    db = DatabaseManager()
    all_rows = db.execute_query("SELECT * FROM sales_transactions WHERE transaction_id = 'TXN0033';")
    assert len(all_rows) == 1
    assert all_rows[0]["status"] == "Returned"

    completed_rows = db.execute_query("SELECT * FROM v_completed_sales WHERE transaction_id = 'TXN0033';")
    assert len(completed_rows) == 0

def test_zero_quantity_handling():
    """Edge Case: Verify that TXN0034 (Quantity: 0) has net_revenue = 0."""
    db = DatabaseManager()
    rows = db.execute_query("SELECT * FROM sales_transactions WHERE transaction_id = 'TXN0034';")
    assert len(rows) == 1
    assert rows[0]["quantity"] == 0
    assert rows[0]["net_revenue"] == 0.0

def test_data_quality_audit_logging():
    """Verify that all data quality issues are persisted in data_quality_audit table."""
    db = DatabaseManager()
    audit_rows = db.execute_query("SELECT * FROM data_quality_audit;")
    assert len(audit_rows) >= 3
    issue_types = {r["issue_type"] for r in audit_rows}
    assert "MISSING_UNIT_PRICE" in issue_types
    assert "ZERO_QUANTITY" in issue_types
    assert "RETURNED_STATUS" in issue_types
