"""The benchmark harness: row limits, statuses and repository picking."""

import json

import pytest

from benchmark import check, data
from benchmark.queries.common import ESQL_LIMIT, EsqlRowLimit, esql_rows


class FakeEsql:
    def __init__(self, n_rows):
        self.n_rows = n_rows

    def query(self, query):
        return {"columns": [{"name": "x"}], "values": [[i] for i in range(self.n_rows)]}


class FakeEs:
    def __init__(self, n_rows):
        self.esql = FakeEsql(n_rows)


def test_esql_rows_under_the_limit():
    assert esql_rows(FakeEs(2), "FROM x") == [{"x": 0}, {"x": 1}]


def test_esql_rows_at_the_limit_raises():
    with pytest.raises(EsqlRowLimit):
        esql_rows(FakeEs(ESQL_LIMIT), "FROM x")


class FakeQuery:
    @staticmethod
    def s1(es, tier, repo_id):
        return {"a": 1}, 1

    @staticmethod
    def s2(es, tier, repo_id):
        return {"a": 2}, 1

    @staticmethod
    def s3(es, tier, repo_id):
        raise ValueError("boom")

    @staticmethod
    def s4(es, tier, repo_id):
        raise EsqlRowLimit("cut off")


@pytest.mark.parametrize(
    ("strategy", "status"),
    [("s1", "pass"), ("s2", "fail"), ("s3", "fail"), ("s4", "limit")],
)
def test_run_one_status(strategy, status):
    row = check.run_one(FakeQuery, strategy, None, "dev", 10, {"a": 1})
    assert row["status"] == status


def _write(records_dir, entity, rows):
    with open(records_dir / f"{entity}.ndjson", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _repo(rid, extra_comments=0):
    """A repository where every query has data, plus optional extra comments."""
    pr = dict(repo_id=rid, author_is_bot=False)
    return {
        "issue": [
            dict(
                pr,
                issue_key=f"{rid}/1",
                author_id=1,
                created_at="2024-01-01T00:00:00Z",
                closed_at="2024-01-03T00:00:00Z",
            )
        ],
        "pull_request": [
            dict(
                pr,
                pr_key=f"{rid}/2",
                author_id=1,
                created_at="2024-01-02T00:00:00Z",
                merged_at="2024-01-03T00:00:00Z",
            ),
            dict(
                pr,
                pr_key=f"{rid}/3",
                author_id=4,
                created_at="2024-01-02T00:00:00Z",
                merged_at="2024-01-03T00:00:00Z",
            ),
        ],
        "review": [
            dict(
                pr, pr_key=f"{rid}/2", author_id=3, submitted_at="2024-01-02T01:00:00Z"
            ),
            dict(
                pr, pr_key=f"{rid}/3", author_id=3, submitted_at="2024-01-02T02:00:00Z"
            ),
        ],
        "comment": [
            dict(
                pr,
                parent_type="issue",
                parent_key=f"{rid}/1",
                author_id=2,
                created_at="2024-01-01T12:00:00Z",
            )
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
    repos = [_repo(10), _repo(20, 5), _repo(30, 50)]
    no_link = _repo(40, 500)
    no_link["link"] = []
    repos.append(no_link)
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
    picks = data.pick_repos(records_dir)
    assert picks["repos"] == {"small": 10, "median": 20, "largest": 30}
    assert picks["eligible"] == 3


def test_load_or_pick_saves_and_reuses(records_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(data, "REPOS_DIR", tmp_path / "repos")
    first = data.load_or_pick("dev", records_dir)
    assert (tmp_path / "repos" / "dev.json").exists()
    (records_dir / "link.ndjson").write_text("")
    assert data.load_or_pick("dev", records_dir) == first
    with pytest.raises(ValueError):
        data.load_or_pick("dev", records_dir, repick=True)
