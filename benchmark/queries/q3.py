"""Q3: median time to first response for first-time vs regular PR contributors"""

from __future__ import annotations

import statistics

from . import activity, q3
from .common import WINDOW_END, WINDOW_START, esql_rows, idx, in_window, search_all


def _group(labels: dict, ttfr: dict) -> dict:
    out = {}
    for group, flag in (("first_time", True), ("regular", False)):
        keys = [k for k, first in labels.items() if first == flag]
        answered = [ttfr[k] for k in keys if ttfr.get(k) is not None]
        out[group] = {
            "prs": len(keys),
            "answered": len(answered),
            "median_seconds": statistics.median(answered) if answered else None,
        }
    return out


def _labels(prs: dict, times: dict) -> dict:
    return {
        k: not any(t < created for t in times.get(author, []))
        for k, (author, created) in prs.items()
    }


def reference(data, repo_id: int) -> dict:
    prs = {
        p["pr_key"]: (p["author_id"], activity.epoch(p["created_at"]))
        for p in data.records("pull_request", repo_id)
        if in_window(p["created_at"]) and not p["author_is_bot"]
    }
    return _group(
        _labels(prs, activity.reference(data, repo_id)), q3.reference(data, repo_id)
    )


def _pr_meta(es, strategy, tier, repo_id):
    hits, n = search_all(
        es,
        idx(strategy, tier, "pull_request"),
        q3._pr_filter(repo_id),
        ["pr_key", "author_id", "created_at"],
        "pr_key",
    )
    return {
        h["_source"]["pr_key"]: (
            h["_source"]["author_id"],
            activity.epoch(h["_source"]["created_at"]),
        )
        for h in hits
    }, n


def _flat(strategy, es, tier, repo_id):
    ttfr, n1 = getattr(q3, strategy)(es, tier, repo_id)
    prs, n2 = _pr_meta(es, strategy, tier, repo_id)
    times, n3 = activity.flat_indexes(es, strategy, tier, repo_id)
    return _group(_labels(prs, times), ttfr), n1 + n2 + n3


def s1(es, tier, repo_id):
    return _flat("s1", es, tier, repo_id)


def s2(es, tier, repo_id):
    return _flat("s2", es, tier, repo_id)


def s3(es, tier, repo_id):
    ttfr, n1 = q3.s3(es, tier, repo_id)
    prs, n2 = _pr_meta(es, "s3", tier, repo_id)
    times, n3 = activity.nested(es, tier, repo_id)
    return _group(_labels(prs, times), ttfr), n1 + n2 + n3


def s4(es, tier, repo_id):
    ttfr, n1 = q3.s4(es, tier, repo_id)
    i, p, c, r = (
        idx("s4", tier, e) for e in ("issue", "pull_request", "comment", "review")
    )
    rows = esql_rows(
        es,
        f"""
        FROM {i},{p},{c},{r} METADATA _index
        | WHERE repo_id == {int(repo_id)} AND author_is_bot == false
        | EVAL t = COALESCE(created_at, submitted_at)
        | WHERE t >= TO_DATETIME("{WINDOW_START}") AND t < TO_DATETIME("{WINDOW_END}")
        | KEEP _index, pr_key, author_id, t
        | INLINE STATS first_at = MIN(t) BY author_id
        | WHERE _index == "{p}"
        | EVAL first_time = first_at == t
        | KEEP pr_key, first_time
        | LIMIT 10000""",
    )
    labels = {row["pr_key"]: row["first_time"] for row in rows if row["pr_key"] in ttfr}
    return _group(labels, ttfr), n1 + 1
