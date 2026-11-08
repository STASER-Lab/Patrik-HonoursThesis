"""Q1: time from PR opened to first response, per PR"""

from __future__ import annotations

from .common import (
    WINDOW_END,
    WINDOW_START,
    composite_all,
    esql_rows,
    idx,
    in_window,
    search_all,
    seconds_between,
    window_filter,
)


def _pr_filter(repo_id: int) -> dict:
    return {
        "bool": {
            "filter": [
                {"term": {"repo_id": repo_id}},
                window_filter(),
                {"term": {"author_is_bot": False}},
            ]
        }
    }


def _finish(prs: dict, first: dict) -> dict:
    return {
        k: (seconds_between(created, first[k]) if k in first else None)
        for k, created in sorted(prs.items())
    }


def reference(data, repo_id: int) -> dict:
    prs = {
        p["pr_key"]: p
        for p in data.records("pull_request", repo_id)
        if in_window(p["created_at"]) and not p["author_is_bot"]
    }
    first: dict = {}

    def consider(pr_key, author_id, is_bot, at):
        pr = prs.get(pr_key)
        if pr and not is_bot and author_id != pr["author_id"]:
            if pr_key not in first or at < first[pr_key]:
                first[pr_key] = at

    for c in data.records("comment", repo_id):
        if c["parent_type"] == "pr":
            consider(
                c["parent_key"], c["author_id"], c["author_is_bot"], c["created_at"]
            )
    for r in data.records("review", repo_id):
        consider(r["pr_key"], r["author_id"], r["author_is_bot"], r["submitted_at"])
    return _finish({k: p["created_at"] for k, p in prs.items()}, first)


def _pr_list(es, strategy, tier, repo_id):
    hits, n = search_all(
        es,
        idx(strategy, tier, "pull_request"),
        _pr_filter(repo_id),
        ["pr_key", "author_id", "created_at"],
        "pr_key",
    )
    return {h["_source"]["pr_key"]: h["_source"] for h in hits}, n


def _min_into(first: dict, key: str, at: str) -> None:
    if key not in first or at < first[key]:
        first[key] = at


def s1(es, tier, repo_id):
    prs, n = _pr_list(es, "s1", tier, repo_id)
    first: dict = {}
    for entity, key_field, time_field, extra in (
        ("comment", "parent_key", "created_at", [{"term": {"parent_type": "pr"}}]),
        ("review", "pr_key", "submitted_at", []),
    ):
        buckets, m = composite_all(
            es,
            idx("s1", tier, entity),
            {
                "bool": {
                    "filter": [
                        {"term": {"repo_id": repo_id}},
                        {"term": {"author_is_bot": False}},
                    ]
                    + extra
                }
            },
            [
                {"pr": {"terms": {"field": key_field}}},
                {"who": {"terms": {"field": "author_id"}}},
            ],
            {"t": {"min": {"field": time_field}}},
        )
        n += m
        for b in buckets:
            pr = prs.get(b["key"]["pr"])
            if pr and b["key"]["who"] != pr["author_id"]:
                _min_into(first, b["key"]["pr"], b["t"]["value_as_string"])
    return _finish({k: p["created_at"] for k, p in prs.items()}, first), n


def s2(es, tier, repo_id):
    prs, n = _pr_list(es, "s2", tier, repo_id)
    not_self = {
        "script": {
            "script": {
                "source": "doc['author_id'].value != doc['parent_author_id'].value"
            }
        }
    }
    first: dict = {}
    for entity, key_field, time_field, extra in (
        ("comment", "parent_key", "created_at", [{"term": {"parent_type": "pr"}}]),
        ("review", "pr_key", "submitted_at", []),
    ):
        buckets, m = composite_all(
            es,
            idx("s2", tier, entity),
            {
                "bool": {
                    "filter": [
                        {"term": {"repo_id": repo_id}},
                        {"term": {"author_is_bot": False}},
                        {"term": {"parent_author_is_bot": False}},
                        window_filter("parent_created_at"),
                        not_self,
                    ]
                    + extra
                }
            },
            [{"pr": {"terms": {"field": key_field}}}],
            {"t": {"min": {"field": time_field}}},
        )
        n += m
        for b in buckets:
            _min_into(first, b["key"]["pr"], b["t"]["value_as_string"])
    return _finish({k: p["created_at"] for k, p in prs.items()}, first), n


def s3(es, tier, repo_id):
    hits, n = search_all(
        es,
        idx("s3", tier, "pull_request"),
        _pr_filter(repo_id),
        [
            "pr_key",
            "author_id",
            "created_at",
            "comments.author_id",
            "comments.author_is_bot",
            "comments.created_at",
            "reviews.author_id",
            "reviews.author_is_bot",
            "reviews.submitted_at",
        ],
        "pr_key",
    )
    prs, first = {}, {}
    for h in hits:
        pr = h["_source"]
        prs[pr["pr_key"]] = pr["created_at"]
        for child, tf in (("comments", "created_at"), ("reviews", "submitted_at")):
            for c in pr.get(child, []):
                if not c["author_is_bot"] and c["author_id"] != pr["author_id"]:
                    _min_into(first, pr["pr_key"], c[tf])
    return _finish(prs, first), n


def s4(es, tier, repo_id):
    c, r, p = (
        idx("s4", tier, "comment"),
        idx("s4", tier, "review"),
        idx("s4", tier, "pull_request"),
    )
    window = (
        f'created_at >= TO_DATETIME("{WINDOW_START}") '
        f'AND created_at < TO_DATETIME("{WINDOW_END}")'
    )
    answered = esql_rows(
        es,
        f"""
        FROM {c},{r}
        | WHERE repo_id == {int(repo_id)} AND author_is_bot == false
          AND (parent_type == "pr" OR parent_type IS NULL)
        | EVAL pr_key = COALESCE(parent_key, pr_key),
        responded_at = COALESCE(created_at, submitted_at)
        | RENAME author_id AS responder_id
        | KEEP pr_key, responder_id, responded_at
        | LOOKUP JOIN {p} ON pr_key
        | WHERE author_is_bot == false AND responder_id != author_id AND {window}
        | STATS first_response = MIN(responded_at) BY pr_key, created_at
        | EVAL seconds = DATE_DIFF("seconds", created_at, first_response)
        | KEEP pr_key, seconds
        | LIMIT 10000""",
    )
    all_prs = esql_rows(
        es,
        f"""
        FROM {p}
        | WHERE repo_id == {int(repo_id)} AND author_is_bot == false AND {window}
        | KEEP pr_key
        | LIMIT 10000""",
    )
    secs = {row["pr_key"]: row["seconds"] for row in answered}
    return {
        row["pr_key"]: secs.get(row["pr_key"])
        for row in sorted(all_prs, key=lambda x: x["pr_key"])
    }, 2
