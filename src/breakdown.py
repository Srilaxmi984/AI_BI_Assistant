"""
breakdown.py - verified SQL for flexible sales questions.

Handles questions such as "top 3 products", "units sold per region",
"lowest revenue category", "revenue in March" or "revenue of Monitor in the South".

How it works:
  1. parse() turns the question into a small Spec: a metric (revenue, units, ...),
     an optional grouping (product, region, ...), optional filters and an ordering.
  2. Filter values are matched against values that really exist in the database,
     and the SQL is built from fixed templates. No text from the question is ever
     placed into a query.
  3. run() executes the SQL through DatabaseManager.execute_query (which validates
     it) and builds the answer text in Python from the returned rows.
"""
import calendar
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("BIAssistant")

# dimension name -> column in v_completed_sales
DIMENSIONS = {
    "product": "product",
    "category": "category",
    "region": "region",
    "channel": "sales_channel",
    "month": "year_month",
}

# words in a question that name a grouping
DIM_WORDS = {
    "product": ("product", "products"),
    "category": ("category", "categories"),
    "region": ("region", "regions", "territory", "territories"),
    "channel": ("channel", "channels"),
    "month": ("month", "months", "monthly"),
}

DIM_PLURAL = {
    "product": "products",
    "category": "categories",
    "region": "regions",
    "channel": "channels",
    "month": "months",
}

# metric -> (SQL expression, column alias, label used in answers, kind)
METRICS = {
    "revenue": ("SUM(net_revenue)", "total_revenue", "revenue", "money"),
    "units": ("SUM(quantity)", "total_units", "units sold", "count"),
    "orders": ("COUNT(*)", "order_count", "orders", "count"),
    "aov": ("ROUND(AVG(net_revenue), 2)", "avg_order_value", "average order value", "money"),
    "discount": ("SUM(discount_amount)", "total_discount", "discounts", "money"),
}

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b")
# "may" is also an ordinary word, so only accept it where it clearly means the month
_MAY_RE = re.compile(
    r"\b(?:in|for|of|during|from|to|and|between|than|vs|versus|with|since|until|by|compare)\s+may\b"
    r"|\bmay\s+(?:2026|revenue|sales|vs|versus)\b|\bmay\W*$|^may\b"
)
_ISO_MONTH_RE = re.compile(r"\b\d{4}-(\d{2})\b")

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM = r"(\d+|" + "|".join(_NUMBER_WORDS) + r")"


def month_numbers(question: str) -> List[int]:
    """Month numbers (1-12) named in the question, e.g. 'march' or '2026-03'."""
    q = question.lower()
    nums = [_MONTHS[m] for m in _MONTH_RE.findall(q)]
    if _MAY_RE.search(q):
        nums.append(5)
    nums += [int(m) for m in _ISO_MONTH_RE.findall(q)]
    return sorted({n for n in nums if 1 <= n <= 12})


@dataclass
class Spec:
    metric: str = "revenue"
    dimension: Optional[str] = None
    filters: Dict[str, List[str]] = field(default_factory=dict)
    limit: Optional[int] = None
    direction: Optional[str] = None          # "desc", "asc", or None if the question has no cue
    missing_months: List[str] = field(default_factory=list)
    multi_dimension: bool = False            # e.g. "by product and region": not supported here


class BreakdownEngine:
    def __init__(self, db):
        self.db = db
        self._values: Optional[Dict[str, List[str]]] = None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _load_values(self) -> Dict[str, List[str]]:
        """Distinct values per dimension, read once from the database."""
        if self._values is not None:
            return self._values
        values: Dict[str, List[str]] = {}
        try:
            for dim, col in DIMENSIONS.items():
                rows = self.db.execute_query(
                    f"SELECT DISTINCT {col} FROM v_completed_sales ORDER BY {col};"
                )
                values[dim] = [str(r[col]) for r in rows if r[col] is not None]
        except Exception:
            logger.exception("Could not load dimension values")
            return {dim: [] for dim in DIMENSIONS}      # not cached, so it is retried
        self._values = values
        return values

    @staticmethod
    def _match_values(known: List[str], q: str) -> List[str]:
        """Known values (or their unique last word, e.g. 'chair') named in the question."""
        found = []
        for v in known:
            names = {v.lower()}
            last = v.lower().split()[-1]
            if sum(1 for o in known if o.lower().split()[-1] == last) == 1:
                names.add(last)
            if any(re.search(r"\b" + re.escape(n) + r"s?\b", q) for n in names):
                found.append(v)
        return found

    @staticmethod
    def _detect_metric(q: str) -> str:
        if re.search(r"\b(average|avg)\b.*\border|\baov\b", q):
            return "aov"
        if "discount" in q:
            return "discount"
        if (re.search(r"\b(number of|how many|count of|total|most|fewest|least|highest|lowest)"
                      r"\s+(?:\w+\s+)?(?:orders?|transactions?)\b", q)
                or re.search(r"\border count\b", q)):
            return "orders"
        if (re.search(r"\b(units?|quantity|quantities|pieces)\b", q)
                or re.search(r"\bitems?\s+sold\b|\bhow many items\b", q)):
            return "units"
        return "revenue"

    @staticmethod
    def _detect_limit(q: str) -> Optional[int]:
        m = (re.search(r"\b(?:top|bottom|best|worst)\s+" + _NUM + r"\b", q)
             or re.search(r"\b" + _NUM + r"\s+(?:best|top|worst|bottom|highest|lowest)\b", q))
        if not m:
            return None
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
        return max(1, min(n, 20))

    def parse(self, question: str) -> Spec:
        q = question.lower()
        values = self._load_values()
        spec = Spec()
        spec.metric = self._detect_metric(q)

        # filters: values that exist in the data and are named in the question
        for dim in ("product", "category", "region", "channel"):
            found = self._match_values(values.get(dim, []), q)
            if found:
                spec.filters[dim] = found

        available = values.get("month", [])
        for n in month_numbers(q):
            ym = next((v for v in available if v.endswith(f"-{n:02d}")), None)
            if ym:
                spec.filters.setdefault("month", []).append(ym)
            elif available:
                spec.missing_months.append(calendar.month_name[n])

        # grouping: a dimension noun in the question that is not already a filter
        nouns = [d for d, words in DIM_WORDS.items()
                 if d not in spec.filters and re.search(r"\b(" + "|".join(words) + r")\b", q)]
        if len(nouns) == 1:
            spec.dimension = nouns[0]
        elif len(nouns) > 1:
            spec.multi_dimension = True

        # ordering and top/bottom N
        if re.search(r"\b(lowest|least|worst|bottom|fewest|smallest|minimum|weakest)\b", q):
            spec.direction = "asc"
        elif re.search(r"\b(highest|most|top|best|largest|biggest|maximum|strongest)\b", q):
            spec.direction = "desc"
        spec.limit = self._detect_limit(q)
        return spec

    @staticmethod
    def wants_breakdown(spec: Spec) -> bool:
        """True when this engine should answer, not the five fixed benchmark queries."""
        if spec.multi_dimension:
            return False
        return bool(
            spec.filters
            or spec.missing_months
            or spec.limit
            or spec.direction == "asc"
            or (spec.dimension == "month" and spec.direction)
            or (spec.dimension and spec.metric in ("units", "orders"))
        )

    # ------------------------------------------------------------------
    # SQL
    # ------------------------------------------------------------------
    @staticmethod
    def _where(spec: Spec) -> str:
        clauses = []
        for dim, vals in spec.filters.items():
            lits = ", ".join("'" + v.replace("'", "''") + "'" for v in vals)
            clauses.append(f"{DIMENSIONS[dim]} IN ({lits})")
        return (" WHERE " + " AND ".join(clauses)) if clauses else ""

    def build_sql(self, spec: Spec) -> str:
        expr, alias, _, _ = METRICS[spec.metric]
        where = self._where(spec)
        if spec.dimension is None:
            extra = "" if spec.metric == "orders" else ", COUNT(*) AS order_count"
            return f"SELECT {expr} AS {alias}{extra} FROM v_completed_sales{where};"
        col = DIMENSIONS[spec.dimension]
        if spec.dimension == "month" and spec.direction is None:
            order = f"ORDER BY {col} ASC"
        else:
            way = "ASC" if spec.direction == "asc" else "DESC"
            order = f"ORDER BY {alias} {way}, {col} ASC"
        limit = f" LIMIT {int(spec.limit)}" if spec.limit else ""
        return (f"SELECT {col}, {expr} AS {alias} FROM v_completed_sales{where} "
                f"GROUP BY {col} {order}{limit};")

    # ------------------------------------------------------------------
    # Running and answer text
    # ------------------------------------------------------------------
    @staticmethod
    def _scope(spec: Spec) -> str:
        parts = [datetime.strptime(ym, "%Y-%m").strftime("%B %Y")
                 for ym in spec.filters.get("month", [])]
        for dim, suffix in (("region", " region"), ("channel", " channel"),
                            ("category", " category"), ("product", "")):
            parts += [v + suffix for v in spec.filters.get(dim, [])]
        return ", ".join(parts) if parts else "all completed orders"

    @staticmethod
    def _fmt(kind: str, value: Any) -> str:
        if kind == "money":
            return f"${float(value):,.2f}"
        return f"{int(value):,}"

    @staticmethod
    def _result(sql, answer, figures, rows, chart_type, chart_config) -> Dict[str, Any]:
        return {
            "intent": "breakdown",
            "sql_query": sql,
            "answer": answer,
            "supporting_figures": figures,
            "table_data": rows,
            "chart_type": chart_type,
            "chart_config": chart_config,
        }

    def _no_data(self, spec: Spec) -> Dict[str, Any]:
        months = self._load_values().get("month", [])
        covered = ""
        if months:
            first = datetime.strptime(months[0], "%Y-%m").strftime("%B %Y")
            last = datetime.strptime(months[-1], "%Y-%m").strftime("%B %Y")
            covered = f" The data covers {first} to {last}."
        answer = f"There is no sales data for {', '.join(spec.missing_months)}.{covered}"
        return self._result("", answer, {}, [], "table", None)

    def run(self, spec: Spec) -> Dict[str, Any]:
        if spec.missing_months:
            return self._no_data(spec)
        sql = self.build_sql(spec)
        rows = self.db.execute_query(sql)
        scope = self._scope(spec)
        if spec.dimension is None:
            return self._scalar(spec, rows, sql, scope)
        return self._grouped(spec, rows, sql, scope)

    def _scalar(self, spec, rows, sql, scope):
        _, alias, label, kind = METRICS[spec.metric]
        row = rows[0] if rows else {}
        value = row.get(alias)
        count = row.get("order_count", 0)
        if value is None or not count:
            return self._result(sql, f"No completed sales found for {scope}.", {}, rows, "table", None)
        if spec.metric == "orders":
            answer = f"There were **{count:,}** completed orders for {scope}."
        else:
            answer = (f"{label.capitalize()} for {scope}: **{self._fmt(kind, value)}** "
                      f"across {count:,} completed orders.")
        figures = {alias: value, "order_count": count, "scope": scope}
        return self._result(sql, answer, figures, rows, "metric_card", None)

    def _grouped(self, spec, rows, sql, scope):
        _, alias, label, kind = METRICS[spec.metric]
        dim = spec.dimension
        col = DIMENSIONS[dim]
        plural = DIM_PLURAL[dim]
        if not rows:
            return self._result(sql, f"No completed sales found for {scope}.", {}, rows, "table", None)

        labels = [str(r[col]) for r in rows]
        values = [r[alias] for r in rows]
        fmt = lambda v: self._fmt(kind, v)
        asc = spec.direction == "asc"
        ctx = f" for {scope}" if spec.filters else ""          # no filters: say nothing extra

        if dim == "month" and spec.direction is None:          # chronological series
            peak = max(rows, key=lambda r: r[alias] or 0)
            answer = (f"{label.capitalize()} by month{ctx}: {fmt(values[0])} in {labels[0]} "
                      f"to {fmt(values[-1])} in {labels[-1]}, peak {fmt(peak[alias])} in {peak[col]}.")
            chart_type = "line"
        elif (spec.limit and spec.limit > 1) or spec.direction is None:   # list every row
            items = ", ".join(f"{l} ({fmt(v)})" for l, v in zip(labels, values))
            if spec.limit:
                head = f"{'Bottom' if asc else 'Top'} {len(rows)} {plural} by {label}"
            else:
                head = f"{label.capitalize()} by {dim}"
            answer = f"{head}{ctx}: {items}."
            chart_type = "bar"
        else:                                                    # single best or worst
            if kind == "money":
                word = "lowest" if asc else "highest"
            else:
                word = "fewest" if asc else "most"
            answer = f"The {dim} with the {word} {label}{ctx} is **{labels[0]}** at {fmt(values[0])}."
            if len(rows) > 1:
                answer += f" ({len(rows)} {plural} compared.)"
            chart_type = "bar"

        series = label.capitalize() + (" ($)" if kind == "money" else "")
        chart_config = {"labels": labels, "values": values, "series_name": series}
        figures = {"metric": spec.metric, "scope": scope, "rows_returned": len(rows), "first_row": rows[0]}
        return self._result(sql, answer, figures, rows, chart_type, chart_config)