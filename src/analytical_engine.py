import re
from typing import Dict, Any, List, Optional, Tuple
from src.database import DatabaseManager
from src.breakdown import BreakdownEngine

class AnalyticalEngine:
    """
    Provides deterministic query generation and statistical calculation
    for business intelligence questions on sales transactions.
    """

    MONTH_NAME_MAP = {
        "january": "2026-01", "jan": "2026-01", "01": "2026-01", "1": "2026-01",
        "february": "2026-02", "feb": "2026-02", "02": "2026-02", "2": "2026-02",
        "march": "2026-03", "mar": "2026-03", "03": "2026-03", "3": "2026-03",
        "april": "2026-04", "apr": "2026-04", "04": "2026-04", "4": "2026-04",
        "may": "2026-05", "05": "2026-05", "5": "2026-05",
        "june": "2026-06", "jun": "2026-06", "06": "2026-06", "6": "2026-06"
    }

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        # Flexible verified questions: filters, top/bottom N, per-group units/orders
        self.breakdown = BreakdownEngine(self.db)

    def get_total_revenue(self) -> Dict[str, Any]:
        """Q1: What is the total revenue?"""
        sql = """
        SELECT 
            COUNT(*) AS total_transactions,
            SUM(quantity) AS total_units_sold,
            SUM(gross_revenue) AS gross_revenue,
            SUM(discount_amount) AS total_discounts,
            SUM(net_revenue) AS total_net_revenue
        FROM v_completed_sales;
        """
        rows = self.db.execute_query(sql)
        data = rows[0] if rows else {}
        net_rev = data.get("total_net_revenue", 0.0)
        gross_rev = data.get("gross_revenue", 0.0)
        discounts = data.get("total_discounts", 0.0)

        answer = (
            f"Total net revenue from completed sales is **${net_rev:,.2f}** "
            f"(Gross revenue: ${gross_rev:,.2f}, Total discounts applied: ${discounts:,.2f} "
            f"across {data.get('total_transactions', 0)} completed transactions)."
        )

        return {
            "intent": "total_revenue",
            "sql_query": sql.strip(),
            "answer": answer,
            "supporting_figures": {
                "total_net_revenue": net_rev,
                "gross_revenue": gross_rev,
                "total_discounts": discounts,
                "total_units_sold": data.get("total_units_sold", 0),
                "transaction_count": data.get("total_transactions", 0)
            },
            "table_data": rows,
            "chart_type": "metric_card"
        }

    def get_highest_revenue_product(self) -> Dict[str, Any]:
        """Q2: Which product generated the highest revenue?"""
        sql = """
        SELECT 
            product,
            category,
            SUM(quantity) AS total_units_sold,
            ROUND(AVG(unit_price), 2) AS avg_unit_price,
            SUM(gross_revenue) AS gross_revenue,
            SUM(discount_amount) AS total_discounts,
            SUM(net_revenue) AS total_revenue
        FROM v_completed_sales
        GROUP BY product, category
        ORDER BY total_revenue DESC;
        """
        rows = self.db.execute_query(sql)
        if not rows:
            return {"error": "No sales data found."}

        top_product = rows[0]
        # Runners-up come from the data (works with any number of products)
        runners = [f"{r['product']} (${r['total_revenue']:,.2f})" for r in rows[1:3]]
        followed = f" It was followed by {' and '.join(runners)}." if runners else ""
        answer = (
            f"The product with the highest revenue is **{top_product['product']}** ({top_product['category']}), "
            f"generating **${top_product['total_revenue']:,.2f}** net revenue from {top_product['total_units_sold']} units sold."
            f"{followed}"
        )

        return {
            "intent": "product_revenue",
            "sql_query": sql.strip(),
            "answer": answer,
            "supporting_figures": {
                "top_product": top_product["product"],
                "top_product_revenue": top_product["total_revenue"],
                "top_product_units": top_product["total_units_sold"],
                "ranking": [
                    {"rank": i + 1, "product": r["product"], "revenue": r["total_revenue"]}
                    for i, r in enumerate(rows)
                ]
            },
            "table_data": rows,
            "chart_type": "bar",
            "chart_config": {
                "labels": [r["product"] for r in rows],
                "values": [r["total_revenue"] for r in rows],
                "series_name": "Net Revenue ($)"
            }
        }

    def get_monthly_revenue_trend(self) -> Dict[str, Any]:
        """Q3: What is the monthly revenue trend?"""
        sql = """
        SELECT 
            year_month,
            SUM(net_revenue) AS monthly_revenue,
            SUM(quantity) AS total_units,
            COUNT(*) AS transaction_count
        FROM v_completed_sales
        GROUP BY year_month
        ORDER BY year_month ASC;
        """
        rows = self.db.execute_query(sql)
        if not rows:
            return {"error": "No sales data found."}

        # Calculate month-over-month changes
        trend_details = []
        prev_rev = None
        for r in rows:
            cur_rev = r["monthly_revenue"]
            if prev_rev is not None:
                diff = cur_rev - prev_rev
                pct = (diff / prev_rev) * 100 if prev_rev else 0.0
            else:
                diff = 0.0
                pct = 0.0
            prev_rev = cur_rev
            trend_details.append({
                "month": r["year_month"],
                "revenue": cur_rev,
                "change": diff,
                "pct_change": round(pct, 2)
            })

        peak_month = max(rows, key=lambda x: x["monthly_revenue"])
        trough_month = min(rows, key=lambda x: x["monthly_revenue"])

        # The strongest-growth month is computed from the data, not typed in
        growth_note = ""
        if len(trend_details) > 1:
            best = max(trend_details[1:], key=lambda t: t["pct_change"])
            if best["pct_change"] > 0:
                growth_note = (
                    f" The strongest growth month was {best['month']} "
                    f"({best['pct_change']:+.1f}% vs the previous month)."
                )

        answer = (
            f"Monthly revenue grew from **${rows[0]['monthly_revenue']:,.2f}** in {rows[0]['year_month']} "
            f"to a peak of **${peak_month['monthly_revenue']:,.2f}** in {peak_month['year_month']}, "
            f"before adjusting to **${rows[-1]['monthly_revenue']:,.2f}** in {rows[-1]['year_month']}."
            f"{growth_note}"
        )

        return {
            "intent": "monthly_revenue_trend",
            "sql_query": sql.strip(),
            "answer": answer,
            "supporting_figures": {
                "peak_month": peak_month["year_month"],
                "peak_revenue": peak_month["monthly_revenue"],
                "lowest_month": trough_month["year_month"],
                "lowest_revenue": trough_month["monthly_revenue"],
                "trend": trend_details
            },
            "table_data": rows,
            "chart_type": "line",
            "chart_config": {
                "labels": [r["year_month"] for r in rows],
                "values": [r["monthly_revenue"] for r in rows],
                "series_name": "Monthly Net Revenue ($)"
            }
        }

    def get_highest_sales_region(self) -> Dict[str, Any]:
        """Q4: Which region generated the highest sales?"""
        sql = """
        SELECT 
            region,
            SUM(net_revenue) AS total_revenue,
            SUM(quantity) AS total_units_sold,
            COUNT(*) AS transaction_count,
            ROUND(AVG(net_revenue), 2) AS avg_order_value
        FROM v_completed_sales
        GROUP BY region
        ORDER BY total_revenue DESC;
        """
        rows = self.db.execute_query(sql)
        if not rows:
            return {"error": "No sales data found."}

        top_region = rows[0]
        total_all_regions = sum(r["total_revenue"] for r in rows)
        top_share = (top_region["total_revenue"] / total_all_regions) * 100 if total_all_regions else 0

        # Region names and order come from the data, not from fixed positions
        parts = [f"{r['region']} (${r['total_revenue']:,.2f})" for r in rows]
        if len(parts) > 2:
            parts[-1] = "and " + parts[-1]
            breakdown_text = ", ".join(parts)
        else:
            breakdown_text = " and ".join(parts)

        answer = (
            f"The **{top_region['region']}** region generated the highest sales with **${top_region['total_revenue']:,.2f}** "
            f"({top_share:.1f}% of total company revenue across {top_region['total_units_sold']} units sold). "
            f"Regional breakdown: {breakdown_text}."
        )

        return {
            "intent": "region_sales",
            "sql_query": sql.strip(),
            "answer": answer,
            "supporting_figures": {
                "top_region": top_region["region"],
                "top_region_revenue": top_region["total_revenue"],
                "regional_shares": [
                    {"region": r["region"], "revenue": r["total_revenue"], "share_pct": round((r["total_revenue"] / total_all_regions) * 100, 2)}
                    for r in rows
                ]
            },
            "table_data": rows,
            "chart_type": "bar",
            "chart_config": {
                "labels": [r["region"] for r in rows],
                "values": [r["total_revenue"] for r in rows],
                "series_name": "Regional Revenue ($)"
            }
        }

    def get_revenue_change_between_months(self, m1: Optional[str] = None, m2: Optional[str] = None) -> Dict[str, Any]:
        """Q5: How did revenue change between two months?"""
        # If no specific months provided, compare the two most recent months or Jan vs Feb as default benchmark
        if not m1 or not m2:
            m1 = "2026-01"
            m2 = "2026-02"

        sql = f"""
        SELECT 
            year_month,
            SUM(net_revenue) AS revenue,
            SUM(quantity) AS units_sold,
            COUNT(*) AS transactions
        FROM v_completed_sales
        WHERE year_month IN ('{m1}', '{m2}')
        GROUP BY year_month
        ORDER BY year_month ASC;
        """
        rows = self.db.execute_query(sql)
        row_map = {r["year_month"]: r for r in rows}

        r1 = row_map.get(m1, {"revenue": 0.0, "units_sold": 0, "transactions": 0})
        r2 = row_map.get(m2, {"revenue": 0.0, "units_sold": 0, "transactions": 0})

        rev1 = r1["revenue"]
        rev2 = r2["revenue"]
        diff = rev2 - rev1
        pct_change = ((diff / rev1) * 100) if rev1 else 0.0
        direction = "increased" if diff >= 0 else "decreased"

        answer = (
            f"Revenue between **{m1}** (${rev1:,.2f}) and **{m2}** (${rev2:,.2f}) "
            f"**{direction} by ${abs(diff):,.2f}** ({pct_change:+.2f}%). "
            f"Total units sold moved from {r1['units_sold']} to {r2['units_sold']}."
        )

        return {
            "intent": "revenue_change_between_months",
            "sql_query": sql.strip(),
            "answer": answer,
            "supporting_figures": {
                "month_1": m1,
                "revenue_1": rev1,
                "month_2": m2,
                "revenue_2": rev2,
                "absolute_change": diff,
                "percent_change": round(pct_change, 2),
                "direction": direction
            },
            "table_data": rows,
            "chart_type": "bar",
            "chart_config": {
                "labels": [m1, m2],
                "values": [rev1, rev2],
                "series_name": "Revenue Comparison ($)"
            }
        }

    def detect_intent(self, question: str) -> Tuple[str, Dict[str, Any]]:
        """
        Extracts intent and parameters from natural language input.

        Order of decisions:
          1. A month the data does not cover (e.g. July) -> clear "no data" answer.
          2. "Change / compare" between months -> Q5.
          3. Questions with filters, top/bottom N, or per-group units/orders -> breakdown.
          4. Questions mixing several groupings -> unknown (goes to the LLM).
          5. The four fixed benchmark phrasings.
        """
        q = question.lower().strip()
        spec = self.breakdown.parse(q)

        # 1. months outside the data
        if spec.missing_months:
            return "breakdown", {"spec": spec}

        # 2. month-over-month change (months are matched as whole words only)
        months = spec.filters.get("month", [])
        if any(w in q for w in ("change", "differ", "grow", "compare")) and (months or "month" in q):
            if len(months) >= 2:
                return "revenue_change_between_months", {"m1": months[0], "m2": months[1]}
            if len(months) == 1:
                m1 = months[0]
                m2 = "2026-02" if m1 == "2026-01" else "2026-01"
                return "revenue_change_between_months", {"m1": min(m1, m2), "m2": max(m1, m2)}
            return "revenue_change_between_months", {"m1": "2026-01", "m2": "2026-02"}

        # 3 and 4. flexible questions
        if spec.multi_dimension:
            return "unknown", {}
        if self.breakdown.wants_breakdown(spec):
            return "breakdown", {"spec": spec}

        # 5. fixed benchmark phrasings
        # Total revenue
        if ("total revenue" in q or "overall revenue" in q or "gross sales" in q or "how much revenue" in q or
            ("total" in q and "sales" in q and "region" not in q and "product" not in q)):
            return "total_revenue", {}

        # Product revenue / highest revenue product
        if ("product" in q and ("highest" in q or "top" in q or "best" in q or "most" in q or "revenue" in q)) or "which product" in q:
            return "highest_revenue_product", {}

        # Monthly trend
        if "monthly" in q or "trend" in q or "month by month" in q or "over time" in q:
            return "monthly_revenue_trend", {}

        # Region sales
        if "region" in q or "territory" in q or "geography" in q or "area" in q:
            return "highest_sales_region", {}

        return "unknown", {}