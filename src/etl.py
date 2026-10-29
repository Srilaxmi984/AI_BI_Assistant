import sqlite3
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from src.config import RAW_DATA_PATH, PROCESSED_DB_PATH, CATALOG_PRICES
from src.database import DatabaseManager

def run_etl(csv_path: Path = RAW_DATA_PATH, db_path: Path = PROCESSED_DB_PATH) -> Dict[str, Any]:
    """
    Ingests raw sales CSV data, performs data cleaning, imputation, validation,
    and loads the clean dataset into SQLite database along with quality audit logs.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Source CSV file not found at: {csv_path}")

    # Read raw CSV
    df = pd.read_csv(csv_path)
    total_raw_rows = len(df)

    audit_logs: List[Dict[str, Any]] = []

    # Clean column names (strip whitespace)
    df.columns = df.columns.str.strip()

    # Parse and normalize dates (input is DD-MM-YYYY, output is standard YYYY-MM-DD)
    def parse_date(date_str):
        try:
            dt = datetime.strptime(str(date_str).strip(), "%d-%m-%Y")
            return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m")
        except Exception:
            return None, None

    date_results = df["Order_date"].apply(parse_date)
    df["order_date_iso"] = [r[0] for r in date_results]
    df["year_month"] = [r[1] for r in date_results]

    # Initialize data quality tracking flags
    df["is_imputed"] = 0
    df["data_quality_flag"] = "VALID"

    # Impute missing Unit_price based on Product Catalog Price Map
    for idx, row in df.iterrows():
        txn_id = row["Transaction_Id"]
        product = str(row["Product"]).strip()
        unit_price = row["Unit_price"]
        quantity = row["Quantity"]
        status = str(row["Status"]).strip()

        # Check for missing unit price
        if pd.isna(unit_price) or str(unit_price).strip() == "":
            catalog_price = CATALOG_PRICES.get(product, 0.0)
            df.at[idx, "Unit_price"] = catalog_price
            df.at[idx, "is_imputed"] = 1
            df.at[idx, "data_quality_flag"] = "IMPUTED_UNIT_PRICE"
            audit_logs.append({
                "transaction_id": txn_id,
                "issue_type": "MISSING_UNIT_PRICE",
                "description": f"Missing unit price for product '{product}'.",
                "action_taken": f"Imputed with catalog price {catalog_price}.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        # Check for zero or negative quantity
        if quantity <= 0:
            df.at[idx, "data_quality_flag"] = "ZERO_QUANTITY"
            audit_logs.append({
                "transaction_id": txn_id,
                "issue_type": "ZERO_QUANTITY",
                "description": f"Quantity is {quantity}.",
                "action_taken": "Flagged as zero quantity; net revenue is 0.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        # Check for Returned status
        if status.lower() == "returned":
            df.at[idx, "data_quality_flag"] = "RETURNED_ORDER"
            audit_logs.append({
                "transaction_id": txn_id,
                "issue_type": "RETURNED_STATUS",
                "description": f"Transaction {txn_id} was marked as Returned.",
                "action_taken": "Flagged; excluded from realized net revenue view.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

    # Ensure numeric columns
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0).astype(int)
    df["Unit_price"] = pd.to_numeric(df["Unit_price"], errors="coerce").fillna(0.0)
    df["Discount_amount"] = pd.to_numeric(df["Discount_amount"], errors="coerce").fillna(0.0)

    # Calculate Gross and Net Revenue
    df["gross_revenue"] = df["Quantity"] * df["Unit_price"]
    df["net_revenue"] = df["gross_revenue"] - df["Discount_amount"]

    # Database Initialization
    db_mgr = DatabaseManager(db_path)
    
    # DDL schema definition
    ddl_script = """
    DROP VIEW IF EXISTS v_completed_sales;
    DROP TABLE IF EXISTS data_quality_audit;
    DROP TABLE IF EXISTS sales_transactions;

    CREATE TABLE sales_transactions (
        transaction_id TEXT PRIMARY KEY,
        order_date TEXT NOT NULL,
        year_month TEXT NOT NULL,
        product TEXT NOT NULL,
        category TEXT NOT NULL,
        region TEXT NOT NULL,
        sales_channel TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        discount_amount REAL NOT NULL DEFAULT 0.0,
        gross_revenue REAL NOT NULL,
        net_revenue REAL NOT NULL,
        status TEXT NOT NULL,
        is_imputed INTEGER NOT NULL DEFAULT 0,
        data_quality_flag TEXT NOT NULL DEFAULT 'VALID'
    );

    CREATE TABLE data_quality_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT NOT NULL,
        issue_type TEXT NOT NULL,
        description TEXT NOT NULL,
        action_taken TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );

    CREATE VIEW v_completed_sales AS
    SELECT 
        transaction_id,
        order_date,
        year_month,
        product,
        category,
        region,
        sales_channel,
        quantity,
        unit_price,
        discount_amount,
        gross_revenue,
        net_revenue,
        status,
        data_quality_flag
    FROM sales_transactions
    WHERE status = 'Completed';

    CREATE INDEX idx_sales_date ON sales_transactions (order_date);
    CREATE INDEX idx_sales_month ON sales_transactions (year_month);
    CREATE INDEX idx_sales_product ON sales_transactions (product);
    CREATE INDEX idx_sales_region ON sales_transactions (region);
    CREATE INDEX idx_sales_status ON sales_transactions (status);
    """

    db_mgr.execute_write_script(ddl_script)

    # Insert cleaned records
    insert_rows = []
    for _, row in df.iterrows():
        insert_rows.append((
            str(row["Transaction_Id"]).strip(),
            row["order_date_iso"],
            row["year_month"],
            str(row["Product"]).strip(),
            str(row["Category"]).strip(),
            str(row["Region"]).strip(),
            str(row["Sales_channel"]).strip(),
            int(row["Quantity"]),
            float(row["Unit_price"]),
            float(row["Discount_amount"]),
            float(row["gross_revenue"]),
            float(row["net_revenue"]),
            str(row["Status"]).strip(),
            int(row["is_imputed"]),
            str(row["data_quality_flag"])
        ))

    with db_mgr.get_connection(read_only=False) as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO sales_transactions (
                transaction_id, order_date, year_month, product, category,
                region, sales_channel, quantity, unit_price, discount_amount,
                gross_revenue, net_revenue, status, is_imputed, data_quality_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, insert_rows)

        if audit_logs:
            audit_tuples = [
                (a["transaction_id"], a["issue_type"], a["description"], a["action_taken"], a["timestamp"])
                for a in audit_logs
            ]
            cursor.executemany("""
                INSERT INTO data_quality_audit (
                    transaction_id, issue_type, description, action_taken, timestamp
                ) VALUES (?, ?, ?, ?, ?)
            """, audit_tuples)
        
        conn.commit()

    summary = {
        "status": "success",
        "total_records_processed": total_raw_rows,
        "completed_sales_count": int((df["Status"] == "Completed").sum()),
        "returned_sales_count": int((df["Status"] == "Returned").sum()),
        "imputed_records_count": int(df["is_imputed"].sum()),
        "quality_issues_detected": len(audit_logs),
        "db_path": str(db_path)
    }
    return summary

if __name__ == "__main__":
    result = run_etl()
    print("ETL Ingestion Summary:", result)
