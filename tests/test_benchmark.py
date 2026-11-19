import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark import check_answers, monitor, repositories
from benchmark.queries import contributors, q1, q2, q3, q4, q5, q6, q7
from benchmark.queries.common import ESQL_LIMIT, EsqlRowLimit, esql_rows
from benchmark.rally import params
from ingest.load.mappings import LAYOUTS

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


def _rows(repos, status="pass", layouts=LAYOUTS):
    return [
        {"query": q, "layout": s, "repo_id": r, "status": status}
        for q in repositories.QUERIES
        for s in layouts
        for r in repos.values()
    ]


def _status(rows):
    return {(x["query"], x["layout"], x["repo_id"]): x["status"] for x in rows}


def test_rally_uses_newest_complete_check(tmp_path):
    repos = {"small": 1, "largest": 2}
    full = tmp_path / "check-dev-20260101-000000.json"
    full.write_text(json.dumps({"results": _rows(repos)}))
    partial = tmp_path / "check-dev-20260102-000000.json"
    partial.write_text(json.dumps({"results": _rows(repos)[:3]}))
    assert params.latest_check("dev", repos, LAYOUTS, tmp_path)[0] == full


def test_rally_check_covers_only_the_timed_layouts(tmp_path):
    repos = {"small": 1}
    without_s3 = ("s1", "s2", "s4")
    all_four = tmp_path / "check-dev-20260101-000000.json"
    all_four.write_text(json.dumps({"results": _rows(repos)}))
    subset = tmp_path / "check-dev-20260102-000000.json"
    subset.write_text(json.dumps({"results": _rows(repos, layouts=without_s3)}))
    assert params.latest_check("dev", repos, without_s3, tmp_path)[0] == subset
    assert params.latest_check("dev", repos, LAYOUTS, tmp_path)[0] == all_four


def test_rally_interleaves_layouts_and_skips_limit():
    status = _status(_rows({"small": 1}))
    status[("q1", "s4", 1)] = "limit"
    combos = params.combinations({"small": 1}, status, LAYOUTS, repetition=1)
    assert [c["layout"] for c in combos[:3]] == ["s2", "s3", "s1"]
    assert ("q1", "s4") not in {(c["query"], c["layout"]) for c in combos}
    assert len(combos) == 7 * 4 - 1


def test_rally_refuses_unverified_answers():
    status = _status(_rows({"small": 1}))
    status[("q3", "s2", 1)] = "fail"
    with pytest.raises(SystemExit):
        params.combinations({"small": 1}, status, LAYOUTS, repetition=0)


def test_rally_times_only_the_selected_layouts():
    status = _status(_rows({"small": 1}))
    status[("q3", "s3", 1)] = "fail"
    without_s3 = ("s1", "s2", "s4")
    combos = params.combinations({"small": 1}, status, without_s3, repetition=1)
    assert {c["layout"] for c in combos} == set(without_s3)
    assert [c["layout"] for c in combos[:3]] == ["s2", "s4", "s1"]
    assert len(combos) == 7 * 3


def test_rally_rejects_unknown_layouts():
    with pytest.raises(SystemExit):
        params.main(["--layouts", "s1,s9"])


def test_rally_mix_holds_each_layouts_timed_combinations():
    status = _status(_rows({"small": 1}))
    status[("q1", "s4", 1)] = "limit"
    mix = params.mixes(params.combinations({"small": 1}, status, LAYOUTS, repetition=0))
    assert len(mix["s1"]) == 7
    assert {"query": "q1", "repo_id": 1} not in mix["s4"]


def _layout_mix():
    path = Path(__file__).parents[1] / "benchmark/rally/track/track.py"
    spec = importlib.util.spec_from_file_location("rally_track", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LayoutMix


def test_rally_mix_is_identical_across_layouts_per_client():
    LayoutMix = _layout_mix()
    mix = [{"query": f"q{i}", "repo_id": i} for i in range(1, 8)]

    def picks(layout, client):
        source = LayoutMix(
            None, {"mix": mix, "seed": 0, "layout": layout, "tier": "dev"}
        )
        part = source.partition(client, 8)
        return [part.params()["query"] for _ in range(20)]

    assert picks("s1", 3) == picks("s4", 3)
    assert picks("s1", 3) != picks("s1", 4)


def node_stats(name, ts_ms, gc_young_ms, read_kb, cpu=50, heap=500_000_000):
    return {
        "name": name,
        "timestamp": ts_ms,
        "os": {"cpu": {"percent": cpu}},
        "process": {"cpu": {"percent": cpu - 10}},
        "jvm": {
            "mem": {"heap_used_in_bytes": heap, "heap_max_in_bytes": 1_000_000_000},
            "gc": {
                "collectors": {
                    "young": {"collection_time_in_millis": gc_young_ms},
                    "old": {"collection_time_in_millis": 0},
                }
            },
        },
        "fs": {
            "io_stats": {
                "total": {
                    "read_operations": read_kb // 4,
                    "write_operations": 0,
                    "read_kilobytes": read_kb,
                    "write_kilobytes": 0,
                }
            }
        },
    }


def test_monitor_flatten_keeps_fields_and_tolerates_missing():
    f = monitor.flatten(node_stats("n1", 1000, 200, 4000, heap=250_000_000))
    assert f["heap_used_pct"] == 25.0
    assert f["gc_young_ms"] == 200 and f["io_read_kb"] == 4000
    assert f["cpu_os_pct"] == 50 and f["cpu_es_pct"] == 40
    bare = monitor.flatten({"name": "mac", "timestamp": 1})  # e.g. no Linux io_stats
    assert bare["io_read_kb"] is None and bare["heap_used_pct"] is None


def test_monitor_summary_per_node():
    rows = [
        {
            "nodes": {
                "n1": monitor.flatten(node_stats("n1", 0, 100, 1000, cpu=20)),
                "n2": monitor.flatten(node_stats("n2", 0, 0, 0, cpu=90)),
            }
        },
        {
            "nodes": {
                "n1": monitor.flatten(
                    node_stats("n1", 5000, 400, 3000, cpu=60, heap=800_000_000)
                )
            }
        },
    ]
    s = monitor.summarise(rows)
    assert s["n1"]["samples"] == 2 and s["n2"]["samples"] == 1
    assert s["n1"]["cpu_os_pct_mean"] == 40.0 and s["n1"]["cpu_os_pct_max"] == 60
    assert s["n1"]["heap_used_pct_max"] == 80.0
    assert s["n1"]["gc_young_ms_total"] == 300 and s["n1"]["io_read_kb_total"] == 2000
    assert s["n2"]["gc_young_ms_total"] == 0


def proc_stat(*cores):
    """/proc/stat text. Each core is (busy, idle). The "cpu" line sums them."""

    def line(name, busy, idle):
        # user nice system idle iowait irq softirq steal guest guest_nice
        return f"{name} {busy} 0 0 {idle} 0 0 0 0 99 99"

    lines = [line("cpu", sum(b for b, _ in cores), sum(i for _, i in cores))]
    lines += [line(f"cpu{n}", b, i) for n, (b, i) in enumerate(cores)]
    return "\n".join(lines + ["intr 123 4 5", "ctxt 678"]) + "\n"


def test_tooling_cpu_total_and_busiest_core(tmp_path):
    f = tmp_path / "stat"
    f.write_text(proc_stat((100, 900), (500, 500)))
    before = monitor.read_proc_stat(f)
    assert before["cpu0"] == (100, 1000)
    f.write_text(proc_stat((110, 990), (600, 500)))
    pct = monitor.cpu_pct(before, monitor.read_proc_stat(f))
    assert pct == {"cpu_pct": 55.0, "busiest_core_pct": 100.0}
    assert monitor.read_proc_stat(tmp_path / "missing") is None  # e.g. macOS
    assert monitor.cpu_pct(None, before) is None


def test_tooling_summary():
    rows = [
        None,
        {"cpu_pct": 20.0, "busiest_core_pct": 40.0},
        {"cpu_pct": 60.0, "busiest_core_pct": 100.0},
    ]
    assert monitor.summarise_tooling(rows) == {
        "samples": 2,
        "cpu_pct_mean": 40.0,
        "cpu_pct_max": 60.0,
        "busiest_core_pct_max": 100.0,
    }
    assert monitor.summarise_tooling([None, None]) is None


class FakeMonitorES:
    def __init__(self, fail_first=False):
        self.calls, self.fail_first = 0, fail_first
        self.nodes = SimpleNamespace(stats=self._stats)

    def _stats(self, metric, filter_path):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise ConnectionError("node restarting")
        t = self.calls * 1000
        return {
            "nodes": {"id1": node_stats("n1", t, 10 * self.calls, 100 * self.calls)}
        }

    def info(self):
        return {"version": {"number": "9.5.4", "build_hash": "abc"}}


def test_monitor_run_samples_until_the_command_ends(tmp_path, monkeypatch):
    exit_code = 3
    monkeypatch.setattr(monitor.connect, "RESULTS_DIR", tmp_path)
    stat = tmp_path / "stat"
    stat.write_text(proc_stat((0, 0)))
    monkeypatch.setattr(monitor, "PROC_STAT", stat)
    es = FakeMonitorES(fail_first=True)
    cmd = [
        sys.executable,
        "-c",
        f"import time, sys; time.sleep(0.5); sys.exit({exit_code})",
    ]
    code, samples_path, summary_path = monitor.run(cmd, "t", es, interval=0.1)
    assert code == exit_code
    lines = [json.loads(x) for x in samples_path.read_text().splitlines()]
    assert lines[0]["command"] == cmd and "environment" in lines[0]
    assert "error" in lines[1]
    good = [x for x in lines[1:] if "nodes" in x]
    assert len(good) >= 3
    summary = json.loads(summary_path.read_text())
    assert summary["exit_code"] == exit_code and summary["sample_errors"] == 1
    assert summary["nodes"]["n1"]["samples"] == len(good)
    assert summary["samples_file"] == samples_path.name
    assert lines[1]["tooling"] is None
    assert "tooling" in lines[2]
    assert summary["tooling"] is None
