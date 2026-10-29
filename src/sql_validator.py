import re
import sqlparse
from sqlparse.sql import Statement
from typing import Tuple, Optional
from src.config import ALLOWED_TABLES, MAX_RESULT_ROWS

class SQLValidationError(Exception):
    """Raised when a generated SQL query fails security or structural validation."""
    pass

class SQLValidator:
    """
    Validates and sanitizes SQL queries to ensure:
    1. Only non-destructive SELECT statements are executed.
    2. No SQL injection, stacked queries, or DDL/DML operations.
    3. Queries only access authorized tables and views.
    """

    DANGEROUS_KEYWORDS = {
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
        "CREATE", "REPLACE", "RENAME", "ATTACH", "DETACH", "PRAGMA",
        "EXEC", "EXECUTE", "VACUUM", "GRANT", "REVOKE", "INTO"
    }

    @classmethod
    def validate_and_sanitize(cls, query: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validates the SQL query.
        Returns:
            (is_valid, sanitized_sql, error_reason)
        """
        if not query or not query.strip():
            return False, "", "Empty SQL query provided."

        # Strip markdown SQL code blocks if the LLM wrapped it
        clean_query = query.strip()
        if clean_query.startswith("```"):
            clean_query = re.sub(r"^```(?:sql)?\s*", "", clean_query, flags=re.IGNORECASE)
            clean_query = re.sub(r"\s*```$", "", clean_query)
        clean_query = clean_query.strip().rstrip(";")

        # 1. Parse using sqlparse
        parsed = sqlparse.parse(clean_query)
        if not parsed:
            return False, "", "Query could not be parsed into a valid SQL AST."

        # 2. Reject multi-statement queries (prevents piggyback attacks)
        if len(parsed) > 1:
            return False, "", "Multiple SQL statements detected. Only a single SELECT query is allowed."

        stmt: Statement = parsed[0]

        # 3. Must be a SELECT statement
        stmt_type = stmt.get_type()
        if stmt_type != "SELECT":
            return False, "", f"Prohibited operation: Statement type '{stmt_type}' is not allowed. Only SELECT queries are permitted."

        # 4. Check for dangerous keywords using case-insensitive token inspection
        flattened_tokens = [t.value.upper() for t in stmt.flatten() if not t.is_whitespace]
        for token in flattened_tokens:
            if token in cls.DANGEROUS_KEYWORDS:
                return False, "", f"Destructive keyword detected: '{token}' is strictly forbidden."

        # 5. Verify table references are within ALLOWED_TABLES
        query_upper = clean_query.upper()
        # Find table names mentioned after FROM or JOIN
        table_matches = re.findall(r"(?:FROM|JOIN)\s+([a-zA-Z0-9_]+)", query_upper)
        if not table_matches:
            # Subqueries or calculations like SELECT 1
            pass
        else:
            for tbl in table_matches:
                tbl_lower = tbl.lower()
                if tbl_lower not in ALLOWED_TABLES:
                    return False, "", f"Access denied: Table or entity '{tbl}' is not in the allowed schema."

        # 6. Append safety limit if no LIMIT clause exists
        if not re.search(r"\bLIMIT\s+\d+", query_upper):
            sanitized_sql = f"{clean_query} LIMIT {MAX_RESULT_ROWS}"
        else:
            sanitized_sql = clean_query

        return True, sanitized_sql, None
