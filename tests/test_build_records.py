"""Step order in build_records type filter -> tier check -> validate -> fold."""

import gzip
import json

from ingest.transform.build_records import main, run

from .test_operations import _pr_with_body, comment_on_pr, pr_obj, pr_opened

IN_TIER, OUTSIDE = 10, 99


def write_gz(path, events, raw_lines=()):
    with gzip.open(path, "wt") as f:
        for e in events:
            f.write(
                json.dumps(e, separators=(",", ":")) + "\n"
            )  # compact, like GH Archive
        for line in raw_lines:
            f.write(line + "\n")
    return path


def outside(event):
    return {**event, "repo": {"id": OUTSIDE, "name": "other/repo"}}


def broken(event):
    return {**event, "payload": {}}


def sample(tmp_path):
    return [
        write_gz(
            tmp_path / "2024-01-10-0.json.gz",
            [
                pr_opened(eid=1),
                comment_on_pr(eid=2),
                broken(pr_opened(eid=3)),
                outside(broken(pr_opened(eid=4))),
                outside(pr_opened(eid=5)),
                {**pr_opened(eid=6), "repo": None},
                {"id": "7", "type": "PushEvent", "repo": {"id": IN_TIER}},
            ],
            raw_lines=['{"type":"IssuesEvent", not json'],
        )
    ]


def test_tier_check_runs_before_validation(tmp_path):
    folder, s = run(sample(tmp_path), keep={IN_TIER})
    assert s["events_accepted"] == 2
    assert s["events_rejected"] == {"empty payload": 1}
    assert s["events_outside_repo_list"] == 2
    assert s["events_no_repo_id"] == 1
    assert s["events_other_types"] == 1
    assert s["events_unparseable"] == 1
    assert set(folder.records["pull_request"]) == {"10/5"}


def test_without_a_repo_list_everything_is_validated(tmp_path):
    _, s = run(sample(tmp_path), keep=None)
    assert s["events_outside_repo_list"] == 0 and s["events_no_repo_id"] == 0
    assert s["events_rejected"] == {"empty payload": 2, "missing repo.id": 1}
    assert s["events_accepted"] == 3


def test_main_writes_records_and_summary(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    sample(raw)
    (tmp_path / "tier.txt").write_text(f"{IN_TIER}\n")
    out = tmp_path / "records"
    assert (
        main([str(raw), "--out", str(out), "--repos", str(tmp_path / "tier.txt")]) == 0
    )
    summary = json.loads((out / "summary.json").read_text())
    assert summary["repo_list"].endswith("tier.txt") and summary["events_accepted"] == 2
    authored = summary["authored_records"]
    assert authored["total"] >= authored["bot"] >= 0
    prs = [
        json.loads(ln) for ln in (out / "pull_request.ndjson").read_text().splitlines()
    ]
    assert [p["pr_key"] for p in prs] == ["10/5"]


def _in_repo(event, repo_id):
    return {**event, "repo": {"id": repo_id, "name": f"org/r{repo_id}"}}


def _fork_pr(repo_id, eid):
    e = _in_repo(pr_opened(eid=eid), repo_id)
    e["payload"]["pull_request"] = pr_obj(fork=True)
    return e


def test_forks_are_dropped_and_events_counted(tmp_path):
    events = [
        pr_opened(eid=1),
        comment_on_pr(eid=2),
        _fork_pr(12, eid=3),
        _in_repo(comment_on_pr(eid=4, cid=79), 12),
    ]
    folder, s = run([write_gz(tmp_path / "a.json.gz", events)], keep=None)
    assert set(folder.records["repository"]) == {IN_TIER}
    assert folder.records["repository"][IN_TIER]["events"] == 2
    assert all(r["repo_id"] == IN_TIER for r in folder.records["comment"].values())
    assert s["forks_dropped"] == {"repos": 1, "events": 2}
    assert s["records"]["repository"] == 1


def test_buckets_give_the_same_records_as_in_memory(tmp_path):
    alice_renamed = {"id": 1, "login": "alice-new", "type": "User"}
    renamed = comment_on_pr(eid=2, user=alice_renamed, at="2024-01-10T13:00:00Z")
    renamed["payload"]["issue"]["user"] = alice_renamed
    events = [
        _in_repo(pr_opened(eid=1), 10),
        _in_repo(renamed, 10),
        _in_repo(pr_opened(eid=3), 11),
        _in_repo(_pr_with_body(6, "Fixes #5", eid=4), 11),
        _in_repo(comment_on_pr(eid=5, cid=78), 11),
        _fork_pr(12, eid=6),
    ]
    raw = tmp_path / "raw"
    raw.mkdir()
    write_gz(raw / "2024-01-10-0.json.gz", events)

    outputs = {}
    for n in (1, 2, 3):
        out = tmp_path / f"out{n}"
        assert main([str(raw), "--out", str(out), "--buckets", str(n)]) == 0
        assert not (out / "buckets").exists()
        summary = json.loads((out / "summary.json").read_text())
        for k in ("seconds", "buckets"):
            summary.pop(k)
        files = {
            p.name: sorted(p.read_text().splitlines()) for p in out.glob("*.ndjson")
        }
        outputs[n] = (files, summary)

    assert outputs[1] == outputs[2] == outputs[3]
    people = [json.loads(ln) for ln in outputs[2][0]["person.ndjson"]]
    assert {p["person_id"]: p["login"] for p in people}[1] == "alice-new"
    assert len(outputs[2][0]["link.ndjson"]) == 1
    assert outputs[2][1]["forks_dropped"] == {"repos": 1, "events": 1}
