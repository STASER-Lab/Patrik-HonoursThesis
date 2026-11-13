"""Q5: per monthly cohort of first-time contributors, the share active again within
90 days
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from . import contributors
from .common import WINDOW_END, WINDOW_START, esql_rows, index_name, share

LAST_COHORT = "2024-09"  # the last cohort whose 90-day follow-up ends within 2024
FOLLOW_UP = 90 * 86_400

informative = bool


def _row(newcomers: int, returned: int) -> dict:
    return {
        "newcomers": newcomers,
        "returned": returned,
        "share": share(returned, newcomers),
    }


def _cohorts(times: dict) -> dict:
    newcomers, returned = Counter(), Counter()
    for ts in times.values():
        cohort = datetime.fromtimestamp(ts[0], UTC).strftime("%Y-%m")
        if cohort <= LAST_COHORT:
            newcomers[cohort] += 1
            returned[cohort] += len(ts) > 1 and ts[1] <= ts[0] + FOLLOW_UP
    return {m: _row(n, returned[m]) for m, n in sorted(newcomers.items())}


def reference(data, repo_id: int) -> dict:
    return _cohorts(contributors.reference(data, repo_id))


def s1(es, tier, repo_id):
    times, n = contributors.flat_indexes(es, "s1", tier, repo_id)
    return _cohorts(times), n


def s2(es, tier, repo_id):
    times, n = contributors.flat_indexes(es, "s2", tier, repo_id)
    return _cohorts(times), n


def s3(es, tier, repo_id):
    times, n = contributors.nested(es, tier, repo_id)
    return _cohorts(times), n


def s4(es, tier, repo_id):
    indices = ",".join(
        index_name("s4", tier, e)
        for e in ("issue", "pull_request", "comment", "review")
    )
    rows = esql_rows(
        es,
        f"""
        FROM {indices}
        | WHERE repo_id == {int(repo_id)} AND author_is_bot == false
        | EVAL t = COALESCE(created_at, submitted_at)
        | WHERE t >= TO_DATETIME("{WINDOW_START}") AND t < TO_DATETIME("{WINDOW_END}")
        | KEEP author_id, t
        | INLINE STATS first_at = MIN(t) BY author_id
        | EVAL again = CASE(t > first_at AND t <= first_at + 90 days, 1, 0)
        | STATS came_back = MAX(again) BY author_id, first_at
        | EVAL cohort = DATE_FORMAT("yyyy-MM", first_at)
        | WHERE cohort <= "{LAST_COHORT}"
        | STATS newcomers = COUNT(*), returned = SUM(came_back) BY cohort
        | SORT cohort
        | LIMIT 10000""",
    )
    return {r["cohort"]: _row(r["newcomers"], r["returned"]) for r in rows}, 1
