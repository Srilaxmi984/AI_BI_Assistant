import uvicorn
from pathlib import Path
from src.config import PROCESSED_DB_PATH, RAW_DATA_PATH, API_HOST, API_PORT
from src.etl import run_etl

def main():
    print("=" * 65)
    print("  🚀 Starting Mini AI Business Intelligence Assistant")
    print("=" * 65)

    # Verify or run ETL
    if not PROCESSED_DB_PATH.exists():
        print(f"[*] Initializing database from {RAW_DATA_PATH}...")
        summary = run_etl()
        print(f"[+] Ingestion complete: {summary['total_records_processed']} records processed, {summary['quality_issues_detected']} issues logged.")
    else:
        print(f"[+] SQLite database found at {PROCESSED_DB_PATH}")

    print(f"\n[+] Serving Web UI & API at: http://{API_HOST}:{API_PORT}")
    print(f"[+] Interactive API docs at:  http://{API_HOST}:{API_PORT}/docs")
    print(f"[+] Press Ctrl+C to stop the server.\n")

    uvicorn.run("src.api:app", host=API_HOST, port=API_PORT, reload=False)

if __name__ == "__main__":
    main()
