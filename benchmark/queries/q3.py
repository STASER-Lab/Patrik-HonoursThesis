"""Q3: share of human PRs merged in the window that were reviewed

A review counts only if a human other than the PR author wrote it.
"""

from __future__ import annotations

from .common import (
    WINDOW_END,
    WINDOW_START,
    composite_all,
    esql_rows,
    in_window,
    index_name,
    search_all,
    share,
    window_filter,
)


def _answer(merged: int, reviewed: int) -> dict:
    return {"merged": merged, "reviewed": reviewed, "share": share(reviewed, merged)}


def reference(data, repo_id: int) -> dict:
    authors = {
        p["pr_key"]: p["author_id"]
        for p in data.records("pull_request", repo_id)
        if in_window(p["merged_at"]) and not p["author_is_bot"]
    }
    reviewed = {
        r["pr_key"]
        for r in data.records("review", repo_id)
        if not r["author_is_bot"]
        and authors.get(r["pr_key"]) not in (None, r["author_id"])
    }
    return _answer(len(authors), len(reviewed))


def informative(answer: dict) -> bool:
    return answer["merged"] > 0 and answer["reviewed"] > 0


def _merged_filter(repo_id):
    return {
        "bool": {
            "filter": [
                {"term": {"repo_id": repo_id}},
                window_filter("merged_at"),
                {"term": {"author_is_bot": False}},
            ]
        }
    }


def s1(es, tier, repo_id):
    hits, n = search_all(
        es,
        index_name("s1", tier, "pull_request"),
        _merged_filter(repo_id),
        ["pr_key", "author_id"],
        "pr_key",
    )
    authors = {h["_source"]["pr_key"]: h["_source"]["author_id"] for h in hits}
    buckets, m = composite_all(
        es,
        index_name("s1", tier, "review"),
        {
            "bool": {
                "filter": [
                    {"term": {"repo_id": repo_id}},
                    {"term": {"author_is_bot": False}},
                ]
            }
        },
        [
            {"pr": {"terms": {"field": "pr_key"}}},
            {"who": {"terms": {"field": "author_id"}}},
        ],
        {},
    )
    reviewed = {
        b["key"]["pr"]
        for b in buckets
        if authors.get(b["key"]["pr"]) not in (None, b["key"]["who"])
    }
    return _answer(len(authors), len(reviewed)), n + m


def s2(es, tier, repo_id):
    pr_idx = index_name("s2", tier, "pull_request")
    rv_idx = index_name("s2", tier, "review")
    not_self = {
        "script": {
            "script": {
                "source": "doc['author_id'].value != doc['parent_author_id'].value"
            }
        }
    }
    resp = es.search(
        index=f"{pr_idx},{rv_idx}",
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
            "reviewed": {
                "filter": {
                    "bool": {
                        "filter": [
                            {"term": {"_index": rv_idx}},
                            window_filter("parent_merged_at"),
                            {"term": {"parent_author_is_bot": False}},
                            {"term": {"author_is_bot": False}},
                            not_self,
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
    return _answer(a["merged"]["doc_count"], len(a["reviewed"]["prs"]["buckets"])), 1


def s3(es, tier, repo_id):
    hits, n = search_all(
        es,
        index_name("s3", tier, "pull_request"),
        _merged_filter(repo_id),
        ["pr_key", "author_id", "reviews.author_id", "reviews.author_is_bot"],
        "pr_key",
    )
    reviewed = sum(
        any(
            not r["author_is_bot"] and r["author_id"] != h["_source"]["author_id"]
            for r in h["_source"].get("reviews", ())
        )
        for h in hits
    )
    return _answer(len(hits), reviewed), n


def s4(es, tier, repo_id):
    rv, pr = index_name("s4", tier, "review"), index_name("s4", tier, "pull_request")
    merged_window = (
        f'merged_at >= TO_DATETIME("{WINDOW_START}") '
        f'AND merged_at < TO_DATETIME("{WINDOW_END}")'
    )
    num = esql_rows(
        es,
        f"""
        FROM {rv}
        | WHERE repo_id == {int(repo_id)} AND author_is_bot == false
        | RENAME author_id AS reviewer_id
        | KEEP pr_key, reviewer_id
        | LOOKUP JOIN {pr} ON pr_key
        | WHERE author_is_bot == false AND reviewer_id != author_id AND {merged_window}
        | STATS reviews = COUNT(*) BY pr_key
        | STATS reviewed = COUNT(*)
        | LIMIT 10000""",
    )
    den = esql_rows(
        es,
        f"""
        FROM {pr}
        | WHERE repo_id == {int(repo_id)} AND author_is_bot == false AND {merged_window}
        | STATS merged = COUNT(*)
        | LIMIT 10000""",
    )
    return _answer(den[0]["merged"], num[0]["reviewed"] if num else 0), 2
