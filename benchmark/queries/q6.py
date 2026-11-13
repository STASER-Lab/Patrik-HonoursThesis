"""Q6: share of issues closed in the window that a merged PR's closing keyword
targets, and the median time from the issue opening to that PR's merge

The merge itself may fall outside the window.
"""

from __future__ import annotations

import statistics

from .common import (
    WINDOW_END,
    WINDOW_START,
    esql_rows,
    in_window,
    index_name,
    keep_earliest,
    search_all,
    share,
    window_filter,
)
from .contributors import epoch


def _format(closed_count: int, times: list[int]) -> dict:
    return {
        "closed": closed_count,
        "via_pr": len(times),
        "share": share(len(times), closed_count),
        "median_seconds_to_merge": statistics.median(times) if times else None,
    }


def _answer(closed: dict, first_merge: dict) -> dict:
    times = [
        first_merge[k] - created for k, created in closed.items() if k in first_merge
    ]
    return _format(len(closed), times)


def reference(data, repo_id: int) -> dict:
    closed = {
        i["issue_key"]: epoch(i["created_at"])
        for i in data.records("issue", repo_id)
        if in_window(i["closed_at"])
    }
    merged = {
        p["pr_key"]: epoch(p["merged_at"])
        for p in data.records("pull_request", repo_id)
        if p["merged_at"]
    }
    first: dict = {}
    for ln in data.records("link", repo_id):
        if (
            ln["target_type"] == "issue"
            and ln["issue_key"] in closed
            and ln["pr_key"] in merged
        ):
            keep_earliest(first, ln["issue_key"], merged[ln["pr_key"]])
    return _answer(closed, first)


def informative(answer: dict) -> bool:
    return answer["via_pr"] > 0


def _closed_issues(es, layout, tier, repo_id):
    hits, n = search_all(
        es,
        index_name(layout, tier, "issue"),
        {
            "bool": {
                "filter": [{"term": {"repo_id": repo_id}}, window_filter("closed_at")]
            }
        },
        ["issue_key", "created_at"],
        "issue_key",
    )
    return {
        s["issue_key"]: epoch(s["created_at"]) for h in hits if (s := h["_source"])
    }, n


def s1(es, tier, repo_id):
    closed, n1 = _closed_issues(es, "s1", tier, repo_id)
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
        ["pr_key", "issue_key"],
        "link_key",
    )
    prs, n3 = search_all(
        es,
        index_name("s1", tier, "pull_request"),
        {
            "bool": {
                "filter": [{"term": {"repo_id": repo_id}}, {"term": {"merged": True}}]
            }
        },
        ["pr_key", "merged_at"],
        "pr_key",
    )
    merged = {h["_source"]["pr_key"]: epoch(h["_source"]["merged_at"]) for h in prs}
    first: dict = {}
    for h in links:
        ln = h["_source"]
        if ln["issue_key"] in closed and ln["pr_key"] in merged:
            keep_earliest(first, ln["issue_key"], merged[ln["pr_key"]])
    return _answer(closed, first), n1 + n2 + n3


def s2(es, tier, repo_id):
    issue_idx = index_name("s2", tier, "issue")
    link_idx = index_name("s2", tier, "link")
    resp = es.search(
        index=f"{issue_idx},{link_idx}",
        size=0,
        query={"term": {"repo_id": repo_id}},
        aggs={
            "closed": {
                "filter": {
                    "bool": {
                        "filter": [
                            {"term": {"_index": issue_idx}},
                            window_filter("closed_at"),
                        ]
                    }
                }
            },
            "via_pr": {
                "filter": {
                    "bool": {
                        "filter": [
                            {"term": {"_index": link_idx}},
                            {"term": {"target_type": "issue"}},
                            {"term": {"pr_merged": True}},
                            window_filter("issue_closed_at"),
                        ]
                    }
                },
                "aggs": {
                    "issues": {
                        # Kept under search.max_buckets (65,536). A repository with more
                        # matching keys would be undercounted
                        "terms": {"field": "issue_key", "size": 65_000},
                        "aggs": {
                            "merge": {"min": {"field": "pr_merged_at"}},
                            "opened": {"min": {"field": "issue_created_at"}},
                        },
                    }
                },
            },
        },
    )
    a = resp["aggregations"]
    times = [
        epoch(b["merge"]["value"]) - epoch(b["opened"]["value"])
        for b in a["via_pr"]["issues"]["buckets"]
    ]
    return _format(a["closed"]["doc_count"], times), 1


def s3(es, tier, repo_id):
    closed, n1 = _closed_issues(es, "s3", tier, repo_id)
    hits, n2 = search_all(
        es,
        index_name("s3", tier, "pull_request"),
        {
            "bool": {
                "filter": [
                    {"term": {"repo_id": repo_id}},
                    {"term": {"merged": True}},
                    {
                        "nested": {
                            "path": "links",
                            "query": {"term": {"links.target_type": "issue"}},
                        }
                    },
                ]
            }
        },
        ["pr_key", "merged_at", "links.issue_key", "links.target_type"],
        "pr_key",
    )
    first: dict = {}
    for h in hits:
        pr = h["_source"]
        for ln in pr.get("links", ()):
            if ln["target_type"] == "issue" and ln["issue_key"] in closed:
                keep_earliest(first, ln["issue_key"], epoch(pr["merged_at"]))
    return _answer(closed, first), n1 + n2


def s4(es, tier, repo_id):
    issue, link, pr = (
        index_name("s4", tier, e) for e in ("issue", "link", "pull_request")
    )
    # Links to PRs and unmerged PRs give a null merge, which MIN ignores
    rows = esql_rows(
        es,
        f"""
        FROM {issue}
        | WHERE repo_id == {int(repo_id)}
          AND closed_at >= TO_DATETIME("{WINDOW_START}")
          AND closed_at < TO_DATETIME("{WINDOW_END}")
        | KEEP issue_key, created_at
        | RENAME created_at AS opened_at
        | LOOKUP JOIN {link} ON issue_key
        | KEEP issue_key, opened_at, pr_key, target_type
        | LOOKUP JOIN {pr} ON pr_key
        | EVAL merge = CASE(target_type == "issue" AND merged_at IS NOT NULL, merged_at)
        | STATS first_merge = MIN(merge) BY issue_key, opened_at
        | EVAL seconds = DATE_DIFF("seconds", opened_at, first_merge)
        | KEEP issue_key, seconds
        | LIMIT 10000""",
    )
    return _format(
        len(rows), [r["seconds"] for r in rows if r["seconds"] is not None]
    ), 1
