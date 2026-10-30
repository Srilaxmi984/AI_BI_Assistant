from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone

from src.agent import SalesBIAgent, MAX_QUESTION_LENGTH
from src.database import DatabaseManager
from src.etl import run_etl
from src.config import PROCESSED_DB_PATH, BASE_DIR

app = FastAPI(
    title="Mini AI Business Intelligence Assistant",
    description="Natural language BI assistant for querying and analyzing enterprise sales transaction data.",
    version="1.0.0"
)

# Enable CORS for cross-origin client apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database and agent
db_mgr = DatabaseManager()
if not PROCESSED_DB_PATH.exists():
    run_etl()

agent = SalesBIAgent(db_mgr)

# Pydantic Request / Response Models
class QueryRequest(BaseModel):
    question: str = Field(
        ...,
        description="Natural language question about sales data",
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
    )

class QueryResponse(BaseModel):
    question: str
    answer: str
    sql_query: str
    supporting_figures: Dict[str, Any]
    table_data: List[Dict[str, Any]]
    chart_type: Optional[str] = "table"
    chart_config: Optional[Dict[str, Any]] = None
    reasoning_trace: List[Dict[str, str]]
    execution_time_ms: float
    data_quality_note: Optional[str] = None
    status: str
    mode: str = "none"  # "llm" | "deterministic" | "none"

# Endpoints
@app.post("/api/query", response_model=QueryResponse, summary="Ask a natural language question")
def ask_question(req: QueryRequest):
    """
    Accepts a natural language question, processes it through the ReAct agent,
    runs validated read-only SQL, and returns structured answer with supporting data.
    """
    try:
        response = agent.process_question(req.question)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal agent error: {str(e)}"
        )

@app.get("/api/kpis", summary="Get executive headline KPIs")
def get_kpis():
    """Returns high-level summary KPIs for the sales dashboard."""
    kpi_query = """
    SELECT 
        SUM(net_revenue) as total_net_revenue,
        SUM(gross_revenue) as total_gross_revenue,
        SUM(discount_amount) as total_discounts,
        SUM(quantity) as total_units_sold,
        COUNT(*) as total_completed_transactions
    FROM v_completed_sales;
    """
    rows = db_mgr.execute_query(kpi_query)
    data = rows[0] if rows else {}

    top_prod_query = """
    SELECT product, SUM(net_revenue) as revenue
    FROM v_completed_sales
    GROUP BY product ORDER BY revenue DESC LIMIT 1;
    """
    top_prod = db_mgr.execute_query(top_prod_query)

    top_reg_query = """
    SELECT region, SUM(net_revenue) as revenue
    FROM v_completed_sales
    GROUP BY region ORDER BY revenue DESC LIMIT 1;
    """
    top_reg = db_mgr.execute_query(top_reg_query)

    return {
        "total_revenue": data.get("total_net_revenue", 0.0),
        "gross_revenue": data.get("total_gross_revenue", 0.0),
        "total_discounts": data.get("total_discounts", 0.0),
        "total_units_sold": data.get("total_units_sold", 0),
        "completed_orders": data.get("total_completed_transactions", 0),
        "top_product": top_prod[0]["product"] if top_prod else "N/A",
        "top_product_revenue": top_prod[0]["revenue"] if top_prod else 0.0,
        "top_region": top_reg[0]["region"] if top_reg else "N/A",
        "top_region_revenue": top_reg[0]["revenue"] if top_reg else 0.0
    }

@app.get("/api/data-quality", summary="Get data quality and audit records")
def get_data_quality():
    """Returns audit log of all identified data anomalies and their remediation."""
    audit_rows = db_mgr.execute_query("SELECT * FROM data_quality_audit ORDER BY id ASC;")
    return {
        "audit_logs": audit_rows,
        "total_issues_logged": len(audit_rows)
    }

@app.get("/api/schema", summary="Get database schema info")
def get_schema():
    """Returns database tables, views, and column definitions."""
    return db_mgr.get_schema_info()

@app.get("/api/sample-queries", summary="Get sample suggested queries")
def get_sample_queries():
    """Returns benchmark sample questions."""
    return [
        {"id": 1, "question": "What is the total revenue?", "category": "Benchmark"},
        {"id": 2, "question": "Which product generated the highest revenue?", "category": "Benchmark"},
        {"id": 3, "question": "What is the monthly revenue trend?", "category": "Benchmark"},
        {"id": 4, "question": "Which region generated the highest sales?", "category": "Benchmark"},
        {"id": 5, "question": "How did revenue change between two months?", "category": "Benchmark"},
        {"id": 6, "question": "Compare January and February revenue", "category": "Deep Dive"},
        {"id": 7, "question": "What are sales by category?", "category": "Exploratory"},
        {"id": 8, "question": "Show performance by sales channel", "category": "Exploratory"},
        {"id": 9, "question": "Show data quality audit logs", "category": "Governance"}
    ]

@app.get("/health", summary="Service health check")
def health():
    return {
        "status": "healthy",
        "database": "connected",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Mount static frontend files
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(str(static_dir / "index.html"))
