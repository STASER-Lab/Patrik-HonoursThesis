"""Q1: issues and PRs opened per month in a repository (single-entity baseline)"""

from __future__ import annotations

from collections import defaultdict

from .common import (
    WINDOW_END,
    WINDOW_START,
    esql_rows,
    in_window,
    index_name,
    window_filter,
)

informative = bool


def _empty() -> dict:
    return defaultdict(lambda: {"issues": 0, "prs": 0})


def _shape(counts: dict) -> dict:
    return dict(sorted(counts.items()))


def reference(data, repo_id: int) -> dict:
    counts = _empty()
    for kind, entity in (("issues", "issue"), ("prs", "pull_request")):
        for r in data.records(entity, repo_id):
            if in_window(r["created_at"]):
                counts[r["created_at"][:7]][kind] += 1
    return _shape(counts)


def _dsl(es, layout: str, tier: str, repo_id: int):
    indices = ",".join(index_name(layout, tier, e) for e in ("issue", "pull_request"))
    resp = es.search(
        index=indices,
        size=0,
        query={"bool": {"filter": [{"term": {"repo_id": repo_id}}, window_filter()]}},
        aggs={
            "by_index": {
                "terms": {"field": "_index", "size": 2},
                "aggs": {
                    "per_month": {
                        "date_histogram": {
                            "field": "created_at",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    }
                },
            }
        },
    )
    counts = _empty()
    for b in resp["aggregations"]["by_index"]["buckets"]:
        kind = "issues" if b["key"].endswith("-issue") else "prs"
        for m in b["per_month"]["buckets"]:
            counts[m["key_as_string"]][kind] = m["doc_count"]
    return _shape(counts), 1


def s1(es, tier, repo_id):
    return _dsl(es, "s1", tier, repo_id)


def s2(es, tier, repo_id):
    return _dsl(es, "s2", tier, repo_id)


def s3(es, tier, repo_id):
    return _dsl(es, "s3", tier, repo_id)


def s4(es, tier, repo_id):
    indices = ",".join(index_name("s4", tier, e) for e in ("issue", "pull_request"))
    rows = esql_rows(
        es,
        f"""
        FROM {indices} METADATA _index
        | WHERE repo_id == {int(repo_id)}
          AND created_at >= TO_DATETIME("{WINDOW_START}")
          AND created_at < TO_DATETIME("{WINDOW_END}")
        | EVAL month = DATE_FORMAT("yyyy-MM", created_at)
        | STATS n = COUNT(*) BY month, _index
        | LIMIT 10000""",
    )
    counts = _empty()
    for r in rows:
        counts[r["month"]]["issues" if r["_index"].endswith("-issue") else "prs"] = r[
            "n"
        ]
    return _shape(counts), 1
