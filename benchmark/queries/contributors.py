"""Each person's activity times in a repository: issues, PRs, comments and reviews by
humans in the window, as sorted epoch seconds per author id
"""

from __future__ import annotations

from collections import defaultdict

from .common import (
    composite_all,
    in_window,
    index_name,
    parse_time,
    search_all,
    window_filter,
)


def epoch(value) -> int:
    """Seconds from an ISO timestamp or from epoch milliseconds (aggregation keys)"""
    if isinstance(value, (int, float)):
        return int(value // 1000)
    return int(parse_time(value).timestamp())


def _add(times: dict, rec: dict, field: str = "created_at") -> None:
    if not rec["author_is_bot"] and in_window(rec[field]):
        times[rec["author_id"]].add(epoch(rec[field]))


def _finish(times: dict) -> dict:
    return {p: sorted(t) for p, t in times.items()}


def reference(data, repo_id: int) -> dict:
    times: dict = defaultdict(set)
    for entity, field in (
        ("issue", "created_at"),
        ("pull_request", "created_at"),
        ("comment", "created_at"),
        ("review", "submitted_at"),
    ):
        for r in data.records(entity, repo_id):
            _add(times, r, field)
    return _finish(times)


def flat_indexes(es, layout: str, tier: str, repo_id: int):
    """For layouts with one index per entity: S1 and S2"""
    times: dict = defaultdict(set)
    requests = 0
    created = ",".join(
        index_name(layout, tier, e) for e in ("issue", "pull_request", "comment")
    )
    for index, field in (
        (created, "created_at"),
        (index_name(layout, tier, "review"), "submitted_at"),
    ):
        buckets, n = composite_all(
            es,
            index,
            {
                "bool": {
                    "filter": [
                        {"term": {"repo_id": repo_id}},
                        {"term": {"author_is_bot": False}},
                        window_filter(field),
                    ]
                }
            },
            [
                {"who": {"terms": {"field": "author_id"}}},
                {"t": {"terms": {"field": field}}},
            ],
            {},
        )
        requests += n
        for b in buckets:
            times[b["key"]["who"]].add(epoch(b["key"]["t"]))
    return _finish(times), requests


def nested(es, tier: str, repo_id: int):
    """For S3, where comments and reviews are nested in their parent"""
    times: dict = defaultdict(set)
    requests = 0
    children_spec = (("comments", "created_at"), ("reviews", "submitted_at"))
    for entity, key, children in (
        ("issue", "issue_key", children_spec[:1]),
        ("pull_request", "pr_key", children_spec),
    ):
        fields = [key, "author_id", "author_is_bot", "created_at"]
        for c, tf in children:
            fields += [f"{c}.author_id", f"{c}.author_is_bot", f"{c}.{tf}"]
        hits, n = search_all(
            es,
            index_name("s3", tier, entity),
            {"term": {"repo_id": repo_id}},
            fields,
            key,
        )
        requests += n
        for h in hits:
            doc = h["_source"]
            _add(times, doc)
            for c, tf in children:
                for child in doc.get(c, ()):
                    _add(times, child, tf)
    return _finish(times), requests
