"""Shared pieces for the query implementations"""

from __future__ import annotations

from datetime import datetime

WINDOW_START = "2024-01-01T00:00:00Z"
WINDOW_END = "2025-06-01T00:00:00Z"
ESQL_LIMIT = 10_000     # ES|QL row return limit


def idx(strategy: str, tier: str, entity: str) -> str:
    return f"{strategy}-{tier}-{entity}"


def in_window(ts: str | None) -> bool:
    return ts is not None and WINDOW_START <= ts < WINDOW_END


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def seconds_between(start: str, end: str) -> int:
    return int((ts(end) - ts(start)).total_seconds())


def window_filter(field: str = "created_at") -> dict:
    return {"range": {field: {"gte": WINDOW_START, "lt": WINDOW_END}}}


def search_all(es, index: str, query: dict, source: list[str], 
               sort_field: str, page: int = 1000):
    hits, requests, after = [], 0, None
    while True:
        body = {"query": query, "_source": source, "size": page, "sort": 
            [{sort_field: "asc"}]}
        if after is not None:
            body["search_after"] = after
        resp = es.search(index=index, **body)
        requests += 1
        batch = resp["hits"]["hits"]
        hits.extend(batch)
        if len(batch) < page:
            return hits, requests
        after = batch[-1]["sort"]


def composite_all(es, index: str, query: dict, sources: 
    list[dict], aggs: dict, page: int = 1000):
    buckets, requests, after = [], 0, None
    while True:
        comp = {"size": page, "sources": sources}
        if after:
            comp["after"] = after
        resp = es.search(index=index, size=0, query=query,
                         aggs={"c": {"composite": comp, "aggs": aggs}})
        requests += 1
        agg = resp["aggregations"]["c"]
        buckets.extend(agg["buckets"])
        after = agg.get("after_key")
        if len(agg["buckets"]) < page or after is None:
            return buckets, requests


def esql_rows(es, query: str) -> list[dict]:
    """Run ES|QL and return rows as dicts. Raises if the row limit was hit"""
    resp = es.esql.query(query=query)
    cols = [c["name"] for c in resp["columns"]]
    rows = [dict(zip(cols, v, strict=True)) for v in resp["values"]]
    if len(rows) >= ESQL_LIMIT:
        raise RuntimeError(f"ES|QL returned {len(rows)} rows, the LIMIT was hit")
    return rows
