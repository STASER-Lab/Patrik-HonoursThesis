"""Q4: median time to first response (Q2) for first-time vs regular PR authors

An author is first-time if they had no activity in the repository before opening
the PR. Activity before the window is not seen.
"""

from __future__ import annotations

import statistics

from . import contributors, q2
from .common import WINDOW_END, WINDOW_START, esql_rows, in_window, index_name


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
        k: times[p["author_id"]][0] == contributors.epoch(p["created_at"])
        for k, p in prs.items()
    }


def reference(data, repo_id: int) -> dict:
    prs = {
        p["pr_key"]: p
        for p in data.records("pull_request", repo_id)
        if in_window(p["created_at"]) and not p["author_is_bot"]
    }
    return _group(
        _labels(prs, contributors.reference(data, repo_id)), q2.reference(data, repo_id)
    )


def informative(answer: dict) -> bool:
    return all(g["answered"] > 0 for g in answer.values())


def _run(layout, es, tier, repo_id):
    ttfr, n1 = getattr(q2, layout)(es, tier, repo_id)
    prs, n2 = q2._pr_list(es, layout, tier, repo_id)
    times, n3 = (
        contributors.nested(es, tier, repo_id)
        if layout == "s3"
        else contributors.flat_indexes(es, layout, tier, repo_id)
    )
    return _group(_labels(prs, times), ttfr), n1 + n2 + n3


def s1(es, tier, repo_id):
    return _run("s1", es, tier, repo_id)


def s2(es, tier, repo_id):
    return _run("s2", es, tier, repo_id)


def s3(es, tier, repo_id):
    return _run("s3", es, tier, repo_id)


def s4(es, tier, repo_id):
    ttfr, n1 = q2.s4(es, tier, repo_id)
    i, p, c, r = (
        index_name("s4", tier, e)
        for e in ("issue", "pull_request", "comment", "review")
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
    # first_at == t counts same-second activity as first-time, as _labels does
    labels = {row["pr_key"]: row["first_time"] for row in rows if row["pr_key"] in ttfr}
    return _group(labels, ttfr), n1 + 1
