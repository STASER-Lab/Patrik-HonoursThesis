"""Q0: issues and PRs opened per month in a repository"""

from __future__ import annotations

from collections import defaultdict

from .common import WINDOW_END, WINDOW_START, esql_rows, idx, in_window, window_filter


def _shape(counts: dict) -> dict:
    return {
        m: {"issues": c.get("issues", 0), "prs": c.get("prs", 0)}
        for m, c in sorted(counts.items())
    }


def reference(data, repo_id: int) -> dict:
    counts: dict = defaultdict(dict)
    for kind, entity in (("issues", "issue"), ("prs", "pull_request")):
        for r in data.records(entity, repo_id):
            if in_window(r["created_at"]):
                m = r["created_at"][:7]
                counts[m][kind] = counts[m].get(kind, 0) + 1
    return _shape(counts)


def informative(answer: dict) -> bool:
    return bool(answer)


def _dsl(es, strategy: str, tier: str, repo_id: int):
    issue_idx, pr_idx = (
        idx(strategy, tier, "issue"),
        idx(strategy, tier, "pull_request"),
    )
    resp = es.search(
        index=f"{issue_idx},{pr_idx}",
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
    counts: dict = defaultdict(dict)
    for b in resp["aggregations"]["by_index"]["buckets"]:
        kind = "issues" if b["key"] == issue_idx else "prs"
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
    issue_idx, pr_idx = idx("s4", tier, "issue"), idx("s4", tier, "pull_request")
    rows = esql_rows(
        es,
        f"""
        FROM {issue_idx},{pr_idx} METADATA _index
        | WHERE repo_id == {int(repo_id)}
          AND created_at >= TO_DATETIME("{WINDOW_START}") AND
        created_at < TO_DATETIME("{WINDOW_END}")
        | EVAL month = DATE_FORMAT("yyyy-MM", created_at)
        | STATS n = COUNT(*) BY month, _index
        | LIMIT 10000""",
    )
    counts: dict = defaultdict(dict)
    for r in rows:
        counts[r["month"]]["issues" if r["_index"] == issue_idx else "prs"] = r["n"]
    return _shape(counts), 1
