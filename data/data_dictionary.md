# Data Dictionary & Business Logic

## 1. Overview
The dataset contains **51 sales transaction records** from January 2026 to June 2026 across various categories, regions, and sales channels.

---

## 2. Table: `sales_transactions`
The primary table storing all processed transaction records with data quality flags and audit indicators.

| Column Name | SQL Type | Nullable | Description / Business Rule |
| :--- | :--- | :--- | :--- |
| `transaction_id` | `TEXT` | No (PK) | Unique transaction identifier (e.g. `TXN0001`). |
| `order_date` | `TEXT` | No | Transaction date normalized to ISO-8601 (`YYYY-MM-DD`). Converted from input `DD-MM-YYYY`. |
| `year_month` | `TEXT` | No | Year and month partition (`YYYY-MM`), indexed for fast monthly aggregation. |
| `product` | `TEXT` | No | Name of the purchased item (e.g., `Laptop Stand`, `Wireless Mouse`, `Monitor`). |
| `category` | `TEXT` | No | Product hierarchy category (`Accessories`, `Furniture`, `Electronics`). |
| `region` | `TEXT` | No | Geographic sales territory (`North`, `South`, `East`, `West`). |
| `sales_channel` | `TEXT` | No | Ingestion channel (`Online`, `Retail`). |
| `quantity` | `INTEGER` | No | Number of units ordered. Zero values are flagged as `ZERO_QUANTITY`. |
| `unit_price` | `REAL` | No | Price per unit in USD. Missing values are imputed using catalog master pricing. |
| `discount_amount` | `REAL` | No | Value of discount deducted from gross revenue (default `0.0`). |
| `gross_revenue` | `REAL` | No | Calculated as `quantity * unit_price`. |
| `net_revenue` | `REAL` | No | Calculated as `(quantity * unit_price) - discount_amount`. Realized commercial revenue. |
| `status` | `TEXT` | No | Order state (`Completed`, `Returned`). |
| `is_imputed` | `INTEGER` | No | Audit flag: `1` if `unit_price` was imputed, `0` otherwise. |
| `data_quality_flag` | `TEXT` | No | Integrity status: `VALID`, `IMPUTED_UNIT_PRICE`, `ZERO_QUANTITY`, `RETURNED_ORDER`. |

---

## 3. View: `v_completed_sales`
Pre-filtered analytical view representing **realized commercial revenue**:
```sql
CREATE VIEW v_completed_sales AS
SELECT 
    transaction_id, order_date, year_month, product, category,
    region, sales_channel, quantity, unit_price, discount_amount,
    gross_revenue, net_revenue, status, data_quality_flag
FROM sales_transactions
WHERE status = 'Completed';
```

---

## 4. Table: `data_quality_audit`
Persistent audit log capturing all anomalies identified during ETL.

| Column Name | Type | Description |
| :--- | :--- | :--- |
| `id` | `INTEGER PK` | Auto-incrementing audit log entry ID. |
| `transaction_id` | `TEXT` | Reference to the affected transaction. |
| `issue_type` | `TEXT` | Category of issue (`MISSING_UNIT_PRICE`, `ZERO_QUANTITY`, `RETURNED_STATUS`). |
| `description` | `TEXT` | Detailed diagnosis of the data anomaly. |
| `action_taken` | `TEXT` | Automated remediation rule applied. |
| `timestamp` | `TEXT` | UTC timestamp of when remediation was executed. |

---

## 5. Master Product Catalog Prices
Used for validation and automated price imputation:

| Product | Category | Catalog Unit Price ($) |
| :--- | :--- | :--- |
| **Desk** | Furniture | $12,500.00 |
| **Keyboard** | Accessories | $900.00 |
| **Laptop Stand** | Accessories | $1,200.00 |
| **Monitor** | Electronics | $9,500.00 |
| **Office Chair** | Furniture | $7,800.00 |
| **USB-C Hub** | Accessories | $1,800.00 |
| **Wireless Mouse** | Accessories | $650.00 |
