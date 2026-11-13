import json
from types import SimpleNamespace

import pytest

from benchmark import check_answers, repositories
from benchmark.queries import contributors, q1, q2, q3, q4, q5, q6, q7
from benchmark.queries.common import ESQL_LIMIT, EsqlRowLimit, esql_rows

PR = {
    "repo_id": 10,
    "author_id": 1,
    "author_is_bot": False,
    "created_at": "2024-01-10T10:00:00Z",
}


def _fake_es(n_rows: int):
    res = {"columns": [{"name": "x"}], "values": [[i] for i in range(n_rows)]}
    return SimpleNamespace(esql=SimpleNamespace(query=lambda query: res))


def test_esql_rows_under_the_limit():
    assert esql_rows(_fake_es(2), "FROM x") == [{"x": 0}, {"x": 1}]


def test_esql_rows_at_the_limit_raises():
    with pytest.raises(EsqlRowLimit):
        esql_rows(_fake_es(ESQL_LIMIT), "FROM x")


class FakeQuery:
    s1 = staticmethod(lambda es, tier, repo_id: ({"a": 1}, 1))
    s2 = staticmethod(lambda es, tier, repo_id: ({"a": 2}, 1))

    @staticmethod
    def s3(es, tier, repo_id):
        raise ValueError("boom")

    @staticmethod
    def s4(es, tier, repo_id):
        raise EsqlRowLimit("cut off")


@pytest.mark.parametrize(
    ("layout", "status"),
    [("s1", "pass"), ("s2", "fail"), ("s3", "fail"), ("s4", "limit")],
)
def test_run_one_status(layout, status):
    row = check_answers.run_one(FakeQuery, layout, None, "dev", 10, {"a": 1})
    assert row["status"] == status


def _write(records_dir, entity, rows):
    (records_dir / f"{entity}.ndjson").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )


def _repo(rid, extra_comments=0):
    base = {"repo_id": rid, "author_is_bot": False}
    return {
        "issue": [
            {
                **base,
                "issue_key": f"{rid}/1",
                "author_id": 1,
                "created_at": "2024-01-01T00:00:00Z",
                "closed_at": "2024-01-03T00:00:00Z",
            }
        ],
        "pull_request": [
            {
                **base,
                "pr_key": f"{rid}/2",
                "author_id": 1,
                "created_at": "2024-01-02T00:00:00Z",
                "merged_at": "2024-01-03T00:00:00Z",
            },
            {
                **base,
                "pr_key": f"{rid}/3",
                "author_id": 4,
                "created_at": "2024-01-02T00:00:00Z",
                "merged_at": "2024-01-03T00:00:00Z",
            },
        ],
        "review": [
            {
                **base,
                "pr_key": f"{rid}/2",
                "author_id": 3,
                "submitted_at": "2024-01-02T01:00:00Z",
            },
            {
                **base,
                "pr_key": f"{rid}/3",
                "author_id": 3,
                "submitted_at": "2024-01-02T02:00:00Z",
            },
        ],
        "comment": [
            {
                **base,
                "parent_type": "issue",
                "parent_key": f"{rid}/1",
                "author_id": 2,
                "created_at": "2024-01-01T12:00:00Z",
            }
        ]
        * (1 + extra_comments),
        "link": [
            {
                "repo_id": rid,
                "pr_key": f"{rid}/2",
                "issue_key": f"{rid}/1",
                "target_type": "issue",
            }
        ],
    }


@pytest.fixture
def records_dir(tmp_path):
    repos = [_repo(10), _repo(20, 5), _repo(30, 50), {**_repo(40, 500), "link": []}]
    for entity in ("issue", "pull_request", "comment", "review", "link"):
        _write(tmp_path, entity, [r for repo in repos for r in repo[entity]])
    sizes = {10: 6, 20: 11, 30: 56, 40: 506}
    _write(
        tmp_path,
        "repository",
        [{"repo_id": rid, "events": n} for rid, n in sizes.items()],
    )
    return tmp_path


def test_pick_repos_ranks_only_eligible(records_dir):
    picks = repositories.pick_repos(records_dir)
    assert picks["repos"] == {"small": 10, "median": 20, "largest": 30}
    assert picks["eligible"] == 3


def test_load_or_pick_saves_and_reuses(records_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(
        repositories, "REPOSITORIES_FILE", tmp_path / "repositories.json"
    )
    first = repositories.load_or_pick("repositories", records_dir)
    assert repositories.REPOSITORIES_FILE.exists()
    (records_dir / "link.ndjson").write_text("")
    assert repositories.load_or_pick("repositories", records_dir) == first
    with pytest.raises(ValueError):
        repositories.load_or_pick("repositories", records_dir, repick=True)


class FakeData:
    def __init__(self, **entities):
        self.entities = entities

    def records(self, entity, repo_id):
        return [r for r in self.entities.get(entity, []) if r["repo_id"] == repo_id]


def _pr_comment(key, author_id, created_at, is_bot=False):
    return {
        "repo_id": 10,
        "parent_type": "pr",
        "parent_key": key,
        "author_id": author_id,
        "author_is_bot": is_bot,
        "created_at": created_at,
    }


def test_q1_counts_issues_and_prs_per_month_in_window():
    d = FakeData(
        issue=[
            {"repo_id": 10, "created_at": "2024-01-05T00:00:00Z"},
            {"repo_id": 10, "created_at": "2024-01-20T00:00:00Z"},
            {"repo_id": 10, "created_at": "2023-12-31T23:59:59Z"},
            {"repo_id": 11, "created_at": "2024-01-05T00:00:00Z"},
        ],
        pull_request=[
            {"repo_id": 10, "created_at": "2024-01-31T23:59:59Z"},
            {"repo_id": 10, "created_at": "2024-03-01T00:00:00Z"},
            {"repo_id": 10, "created_at": "2025-05-01T00:00:00Z"},
        ],
    )
    assert q1.reference(d, 10) == {
        "2024-01": {"issues": 2, "prs": 1},
        "2024-03": {"issues": 0, "prs": 1},
    }


def test_q2_first_response_rules():
    d = FakeData(
        pull_request=[
            {**PR, "pr_key": "10/1"},
            {**PR, "pr_key": "10/2"},
            {**PR, "pr_key": "10/3", "author_is_bot": True},
            {**PR, "pr_key": "10/4", "created_at": "2023-12-01T00:00:00Z"},
        ],
        comment=[
            _pr_comment("10/1", 1, "2024-01-10T10:01:00Z"),
            _pr_comment("10/1", 3, "2024-01-10T10:02:00Z", is_bot=True),
            _pr_comment("10/1", 2, "2024-01-10T11:00:00Z"),
        ],
        review=[
            {
                **PR,
                "pr_key": "10/1",
                "author_id": 4,
                "submitted_at": "2024-01-10T10:30:00Z",
            }
        ],
    )
    assert q2.reference(d, 10) == {"10/1": 1800, "10/2": None}


def test_q3_counts_only_human_merged_prs_reviewed_by_others():
    merged = "2024-01-10T12:00:00Z"
    d = FakeData(
        pull_request=[
            {**PR, "pr_key": "10/1", "merged_at": merged},
            {**PR, "pr_key": "10/2", "merged_at": merged},
            {**PR, "pr_key": "10/3", "merged_at": None},
            {**PR, "pr_key": "10/4", "merged_at": merged, "author_is_bot": True},
        ],
        review=[
            {"repo_id": 10, "pr_key": "10/1", "author_id": 2, "author_is_bot": False},
            {"repo_id": 10, "pr_key": "10/2", "author_id": 1, "author_is_bot": False},
            {"repo_id": 10, "pr_key": "10/2", "author_id": 3, "author_is_bot": True},
        ],
    )
    assert q3.reference(d, 10) == {"merged": 2, "reviewed": 1, "share": 0.5}


def test_activity_ignores_bots_and_outside_window():
    d = FakeData(
        issue=[
            {**PR, "created_at": "2024-01-01T00:00:00Z"},
            {**PR, "created_at": "2023-06-01T00:00:00Z"},
        ],
        comment=[
            {
                **PR,
                "author_id": 2,
                "author_is_bot": True,
                "created_at": "2024-01-02T00:00:00Z",
            },
            {**PR, "created_at": "2024-01-01T00:00:00Z"},
        ],
    )
    assert contributors.reference(d, 10) == {1: [1704067200]}


def test_q4_labels_first_time_by_earlier_activity():
    d = FakeData(
        pull_request=[
            {**PR, "pr_key": "10/1", "author_id": 1},
            {**PR, "pr_key": "10/2", "author_id": 5},
        ],
        issue=[{**PR, "author_id": 5, "created_at": "2024-01-05T00:00:00Z"}],
        comment=[
            _pr_comment("10/1", 9, "2024-01-10T10:10:00Z"),
            _pr_comment("10/2", 9, "2024-01-10T11:00:00Z"),
        ],
    )
    assert q4.reference(d, 10) == {
        "first_time": {"prs": 1, "answered": 1, "median_seconds": 600},
        "regular": {"prs": 1, "answered": 1, "median_seconds": 3600},
    }


def test_q5_cohorts_and_90_day_return():
    d = FakeData(
        comment=[
            _pr_comment("10/9", 1, "2024-01-05T00:00:00Z"),
            _pr_comment("10/9", 1, "2024-03-01T00:00:00Z"),
            _pr_comment("10/9", 2, "2024-01-20T00:00:00Z"),
            _pr_comment("10/9", 2, "2024-06-01T00:00:00Z"),
            _pr_comment("10/9", 3, "2024-10-02T00:00:00Z"),
        ]
    )
    assert q5.reference(d, 10) == {
        "2024-01": {"newcomers": 2, "returned": 1, "share": 0.5}
    }


def test_q6_issue_closed_via_merged_pr():
    issue = {
        "repo_id": 10,
        "created_at": "2024-01-01T00:00:00Z",
        "closed_at": "2024-01-03T00:00:00Z",
    }
    d = FakeData(
        issue=[
            {**issue, "issue_key": "10/1"},
            {**issue, "issue_key": "10/2"},
            {**issue, "issue_key": "10/3", "closed_at": None},
            {**issue, "issue_key": "10/4"},
        ],
        pull_request=[
            {"repo_id": 10, "pr_key": "10/5", "merged_at": "2024-01-02T00:00:00Z"},
            {"repo_id": 10, "pr_key": "10/6", "merged_at": "2024-01-01T12:00:00Z"},
            {"repo_id": 10, "pr_key": "10/7", "merged_at": None},
        ],
        link=[
            {"repo_id": 10, "pr_key": p, "issue_key": i, "target_type": "issue"}
            for p, i in (
                ("10/5", "10/1"),
                ("10/6", "10/1"),
                ("10/7", "10/4"),
                ("10/5", "10/3"),
            )
        ],
    )
    assert q6.reference(d, 10) == {
        "closed": 3,
        "via_pr": 1,
        "share": 0.3333,
        "median_seconds_to_merge": 43200,
    }


def test_q7_merged_prs_that_close_an_issue():
    merged = "2024-02-01T00:00:00Z"
    d = FakeData(
        pull_request=[
            {**PR, "pr_key": "10/1", "merged_at": merged},
            {**PR, "pr_key": "10/2", "merged_at": merged},
            {**PR, "pr_key": "10/3", "merged_at": merged},
            {**PR, "pr_key": "10/4", "merged_at": "2023-12-01T00:00:00Z"},
            {**PR, "pr_key": "10/5", "merged_at": None},
            {**PR, "pr_key": "10/6", "merged_at": merged},
            {**PR, "pr_key": "10/7", "merged_at": merged},
            {**PR, "pr_key": "10/8", "merged_at": merged, "author_is_bot": True},
        ],
        link=[
            {"repo_id": 10, "pr_key": "10/1", "target_type": "issue"},
            {"repo_id": 10, "pr_key": "10/2", "target_type": "pr"},
            {"repo_id": 10, "pr_key": "10/3", "target_type": "unknown"},
            {"repo_id": 10, "pr_key": "10/4", "target_type": "issue"},
            {"repo_id": 10, "pr_key": "10/5", "target_type": "issue"},
            {"repo_id": 10, "pr_key": "10/6", "target_type": "issue"},
            {"repo_id": 10, "pr_key": "10/6", "target_type": "issue"},
            {"repo_id": 10, "pr_key": "10/8", "target_type": "issue"},
        ],
    )
    assert q7.reference(d, 10) == {"merged": 5, "closing": 2, "share": 0.4}


def test_q7_no_merged_prs():
    assert q7.reference(FakeData(), 10) == {"merged": 0, "closing": 0, "share": None}
