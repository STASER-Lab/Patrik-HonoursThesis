"""Query window, pagination and helpers shared by every query"""

from __future__ import annotations

from datetime import datetime

from ingest.load.mappings import index_name as index_name

WINDOW_START = "2024-01-01T00:00:00Z"
# 2024 plus January to April 2025, the months update replay adds to a loaded tier
WINDOW_END = "2025-05-01T00:00:00Z"
ESQL_LIMIT = 10_000  # esql.query.result_truncation_max_size default


def in_window(ts: str | None) -> bool:
    """Compares strings, so `ts` must be in GH Archive's UTC format:
    YYYY-MM-DDTHH:MM:SSZ"""
    return ts is not None and WINDOW_START <= ts < WINDOW_END


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def seconds_between(start: str, end: str) -> int:
    return int((parse_time(end) - parse_time(start)).total_seconds())


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def keep_earliest(first: dict, key, at) -> None:
    first[key] = min(at, first.get(key, at))


def window_filter(field: str = "created_at") -> dict:
    return {"range": {field: {"gte": WINDOW_START, "lt": WINDOW_END}}}


def search_all(
    es, index: str, query: dict, source: list[str], sort_field: str, page: int = 1000
):
    """Every hit for `query` as (hits, requests), paged with search_after.

    `sort_field` must be unique per document, or pages can skip or repeat hits.
    """
    hits, requests, after = [], 0, None
    while True:
        resp = es.search(
            index=index,
            query=query,
            _source=source,
            size=page,
            sort=[{sort_field: "asc"}],
            **({"search_after": after} if after else {}),
        )
        requests += 1
        batch = resp["hits"]["hits"]
        hits.extend(batch)
        if len(batch) < page:
            return hits, requests
        after = batch[-1]["sort"]


def composite_all(
    es, index: str, query: dict, sources: list[dict], aggs: dict, page: int = 1000
):
    """Every composite aggregation bucket as (buckets, requests)"""
    buckets, requests, after = [], 0, None
    while True:
        comp = {"size": page, "sources": sources}
        if after:
            comp["after"] = after
        resp = es.search(
            index=index,
            size=0,
            query=query,
            aggs={"c": {"composite": comp, "aggs": aggs}},
        )
        requests += 1
        agg = resp["aggregations"]["c"]
        buckets.extend(agg["buckets"])
        if len(agg["buckets"]) < page or not (after := agg.get("after_key")):
            return buckets, requests


class EsqlRowLimit(RuntimeError):
    """An ES|QL answer was cut off at the row limit, so it is not exact. This is a
    limit of the layout (RQ1 "not supported"), not a wrong answer."""


def esql_rows(es, query: str) -> list[dict]:
    """Run ES|QL and return rows as dicts. A full page of ESQL_LIMIT rows cannot be
    told apart from a truncated one, so it raises EsqlRowLimit."""
    resp = es.esql.query(query=query)
    vals = resp["values"]
    if len(vals) >= ESQL_LIMIT:
        raise EsqlRowLimit(f"ES|QL returned {len(vals)} rows, the row limit was hit")
    cols = [c["name"] for c in resp["columns"]]
    return [dict(zip(cols, v, strict=True)) for v in vals]
