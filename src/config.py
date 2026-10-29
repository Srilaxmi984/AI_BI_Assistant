import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_PATH = DATA_DIR / "raw" / "sales_data.csv"
PROCESSED_DB_PATH = DATA_DIR / "processed" / "sales.db"

# API & Server Configuration
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8000))
DEBUG_MODE = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

# Known Product Catalog Prices for Imputation / Validation
CATALOG_PRICES = {
    "Desk": 12500.0,
    "Keyboard": 900.0,
    "Laptop Stand": 1200.0,
    "Monitor": 9500.0,
    "Office Chair": 7800.0,
    "USB-C Hub": 1800.0,
    "Wireless Mouse": 650.0
}

# AI Engine Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto") # auto, gemini, openai, fallback
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Security / SQL Guardrails
ALLOWED_TABLES = {"sales_transactions", "v_completed_sales", "data_quality_audit"}
MAX_RESULT_ROWS = 1000
QUERY_TIMEOUT_SECONDS = 5
