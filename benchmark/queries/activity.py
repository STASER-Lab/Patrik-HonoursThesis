"""Contribution history per person in a repository"""

from __future__ import annotations

from collections import defaultdict

from .common import composite_all, idx, in_window, search_all, ts, window_filter


def epoch(value) -> int:
    if isinstance(value, (int, float)):
        return int(value // 1000)
    return int(ts(value).timestamp())


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
            if not r["author_is_bot"] and in_window(r[field]):
                times[r["author_id"]].add(epoch(r[field]))
    return _finish(times)


def flat_indexes(es, strategy: str, tier: str, repo_id: int):
    times: dict = defaultdict(set)
    requests = 0
    targets = (
        (
            ",".join(
                idx(strategy, tier, e) for e in ("issue", "pull_request", "comment")
            ),
            "created_at",
        ),
        (idx(strategy, tier, "review"), "submitted_at"),
    )
    for index, field in targets:
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
    times: dict = defaultdict(set)
    requests = 0
    for entity, key, children in (
        ("issue", "issue_key", ("comments",)),
        ("pull_request", "pr_key", ("comments", "reviews")),
    ):
        fields = [key, "author_id", "author_is_bot", "created_at"]
        for c in children:
            tf = "submitted_at" if c == "reviews" else "created_at"
            fields += [f"{c}.author_id", f"{c}.author_is_bot", f"{c}.{tf}"]
        hits, n = search_all(
            es, idx("s3", tier, entity), {"term": {"repo_id": repo_id}}, fields, key
        )
        requests += n
        for h in hits:
            doc = h["_source"]
            if not doc["author_is_bot"] and in_window(doc["created_at"]):
                times[doc["author_id"]].add(epoch(doc["created_at"]))
            for c in children:
                tf = "submitted_at" if c == "reviews" else "created_at"
                for child in doc.get(c, []):
                    if not child["author_is_bot"] and in_window(child[tf]):
                        times[child["author_id"]].add(epoch(child[tf]))
    return _finish(times), requests
