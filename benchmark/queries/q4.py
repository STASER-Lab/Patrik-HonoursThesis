"""Q4: share of a month's first-time contributors who contribute again within 90 days"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from . import activity
from .common import WINDOW_END, WINDOW_START, esql_rows, idx

LAST_COHORT = "2024-09"
FOLLOW_UP = 90 * 86_400


def _cohorts(times: dict) -> dict:
    newcomers: Counter[str] = Counter()
    returned: Counter[str] = Counter()
    for person_times in times.values():
        first = person_times[0]
        cohort = datetime.fromtimestamp(first, UTC).strftime("%Y-%m")
        if cohort > LAST_COHORT:
            continue
        newcomers[cohort] += 1
        returned[cohort] += any(
            first < t <= first + FOLLOW_UP for t in person_times[1:]
        )
    return {
        m: {"newcomers": n, "returned": returned[m], "share": round(returned[m] / n, 4)}
        for m, n in sorted(newcomers.items())
    }


def reference(data, repo_id: int) -> dict:
    return _cohorts(activity.reference(data, repo_id))


def s1(es, tier, repo_id):
    times, n = activity.flat_indexes(es, "s1", tier, repo_id)
    return _cohorts(times), n


def s2(es, tier, repo_id):
    times, n = activity.flat_indexes(es, "s2", tier, repo_id)
    return _cohorts(times), n


def s3(es, tier, repo_id):
    times, n = activity.nested(es, tier, repo_id)
    return _cohorts(times), n


def s4(es, tier, repo_id):
    i, p, c, r = (
        idx("s4", tier, e) for e in ("issue", "pull_request", "comment", "review")
    )
    rows = esql_rows(
        es,
        f"""
        FROM {i},{p},{c},{r}
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
        | LIMIT 10000""",
    )
    return {
        row["cohort"]: {
            "newcomers": row["newcomers"],
            "returned": row["returned"],
            "share": round(row["returned"] / row["newcomers"], 4),
        }
        for row in sorted(rows, key=lambda x: x["cohort"])
    }, 1
