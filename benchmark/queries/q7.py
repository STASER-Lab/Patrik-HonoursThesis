"""Q7: share of human PRs merged in the window whose body closes at least one issue"""

from __future__ import annotations

from .common import (
    WINDOW_END,
    WINDOW_START,
    esql_rows,
    in_window,
    index_name,
    search_all,
    share,
    window_filter,
)
from .q3 import _merged_filter


def _answer(merged: int, closing: int) -> dict:
    return {"merged": merged, "closing": closing, "share": share(closing, merged)}


def reference(data, repo_id: int) -> dict:
    merged = {
        p["pr_key"]
        for p in data.records("pull_request", repo_id)
        if in_window(p["merged_at"]) and not p["author_is_bot"]
    }
    closing = {
        ln["pr_key"]
        for ln in data.records("link", repo_id)
        if ln["target_type"] == "issue" and ln["pr_key"] in merged
    }
    return _answer(len(merged), len(closing))


def informative(answer: dict) -> bool:
    return answer["closing"] > 0


def s1(es, tier, repo_id):
    prs, n1 = search_all(
        es,
        index_name("s1", tier, "pull_request"),
        _merged_filter(repo_id),
        ["pr_key"],
        "pr_key",
    )
    merged = {h["_source"]["pr_key"] for h in prs}
    links, n2 = search_all(
        es,
        index_name("s1", tier, "link"),
        {
            "bool": {
                "filter": [
                    {"term": {"repo_id": repo_id}},
                    {"term": {"target_type": "issue"}},
                ]
            }
        },
        ["pr_key"],
        "link_key",
    )
    closing = {h["_source"]["pr_key"] for h in links} & merged
    return _answer(len(merged), len(closing)), n1 + n2


def s2(es, tier, repo_id):
    pr_idx = index_name("s2", tier, "pull_request")
    link_idx = index_name("s2", tier, "link")
    resp = es.search(
        index=f"{pr_idx},{link_idx}",
        size=0,
        query={"term": {"repo_id": repo_id}},
        aggs={
            "merged": {
                "filter": {
                    "bool": {
                        "filter": [
                            {"term": {"_index": pr_idx}},
                            window_filter("merged_at"),
                            {"term": {"author_is_bot": False}},
                        ]
                    }
                }
            },
            "closing": {
                "filter": {
                    "bool": {
                        "filter": [
                            {"term": {"_index": link_idx}},
                            {"term": {"target_type": "issue"}},
                            window_filter("pr_merged_at"),
                            {"term": {"pr_author_is_bot": False}},
                        ]
                    }
                },
                # Kept under search.max_buckets (65,536). A repository with more
                # matching keys would be undercounted
                "aggs": {"prs": {"terms": {"field": "pr_key", "size": 65_000}}},
            },
        },
    )
    a = resp["aggregations"]
    return _answer(a["merged"]["doc_count"], len(a["closing"]["prs"]["buckets"])), 1


def s3(es, tier, repo_id):
    resp = es.search(
        index=index_name("s3", tier, "pull_request"),
        size=0,
        track_total_hits=True,
        query=_merged_filter(repo_id),
        aggs={
            "closing": {
                "filter": {
                    "nested": {
                        "path": "links",
                        "query": {"term": {"links.target_type": "issue"}},
                    }
                }
            }
        },
    )
    merged = resp["hits"]["total"]["value"]
    return _answer(merged, resp["aggregations"]["closing"]["doc_count"]), 1


def s4(es, tier, repo_id):
    pr, link = index_name("s4", tier, "pull_request"), index_name("s4", tier, "link")
    rows = esql_rows(
        es,
        f"""
        FROM {pr}
        | WHERE repo_id == {int(repo_id)}
          AND merged_at >= TO_DATETIME("{WINDOW_START}")
          AND merged_at < TO_DATETIME("{WINDOW_END}")
          AND author_is_bot == false
        | KEEP pr_key
        | LOOKUP JOIN {link} ON pr_key
        | EVAL closes = CASE(target_type == "issue", 1, 0)
        | STATS closes = MAX(closes) BY pr_key
        | STATS merged = COUNT(*), closing = SUM(closes)
        | LIMIT 10000""",
    )
    return _answer(rows[0]["merged"], rows[0]["closing"] or 0), 1
