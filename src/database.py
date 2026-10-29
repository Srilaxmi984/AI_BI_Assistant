import sqlite3
import pandas as pd
from typing import List, Dict, Any, Tuple
from pathlib import Path
from src.config import PROCESSED_DB_PATH

class DatabaseManager:
    """
    Manages connections and query execution on the SQLite database.
    Supports strictly read-only execution for analytical querying.
    """

    def __init__(self, db_path: Path = PROCESSED_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self, read_only: bool = True) -> sqlite3.Connection:
        """
        Creates a SQLite connection.
        If read_only is True, sets PRAGMA query_only = ON for database-level protection.
        """
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        if read_only:
            # Enforce read-only constraint at the database engine level
            conn.execute("PRAGMA query_only = ON;")
        return conn

    def execute_query(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """
        Executes a read-only query and returns rows as dictionaries.
        """
        with self.get_connection(read_only=True) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def execute_query_df(self, query: str, params: Tuple = ()) -> pd.DataFrame:
        """
        Executes a read-only query and returns a pandas DataFrame.
        """
        with self.get_connection(read_only=True) as conn:
            return pd.read_sql_query(query, conn, params=params)

    def execute_write_script(self, script: str):
        """
        Used strictly during ETL / schema setup to run migration scripts.
        """
        with self.get_connection(read_only=False) as conn:
            conn.executescript(script)
            conn.commit()

    def get_schema_info(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Returns table schema details for LLM prompt context and documentation.
        """
        with self.get_connection(read_only=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'")
            entities = cursor.fetchall()
            schema = {}
            for entity in entities:
                name = entity["name"]
                cursor.execute(f"PRAGMA table_info({name})")
                cols = cursor.fetchall()
                schema[name] = [
                    {"name": col["name"], "type": col["type"], "notnull": bool(col["notnull"])}
                    for col in cols
                ]
            return schema
