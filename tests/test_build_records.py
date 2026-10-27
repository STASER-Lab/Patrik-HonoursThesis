"""Step order in build_records type filter -> tier check -> validate -> fold."""

import gzip
import json

from ingest.transform.build_records import main, run
from tests.test_transform import comment_on_pr, pr_opened

IN_TIER, OUTSIDE = 10, 99


def write_gz(path, events, raw_lines=()):
    with gzip.open(path, "wt") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")   # compact, like GH Archive
        for line in raw_lines:
            f.write(line + "\n")
    return path


def outside(event):
    return {**event, "repo": {"id": OUTSIDE, "name": "other/repo"}}


def broken(event):
    return {**event, "payload": {}}


def sample(tmp_path):
    return [write_gz(tmp_path / "2024-01-10-0.json.gz", [
        pr_opened(eid=1),
        comment_on_pr(eid=2),
        broken(pr_opened(eid=3)),
        outside(broken(pr_opened(eid=4))),
        outside(pr_opened(eid=5)),
        {**pr_opened(eid=6), "repo": None},
        {"id": "7", "type": "PushEvent", "repo": {"id": IN_TIER}},
    ], raw_lines=['{"type":"IssuesEvent", not json'])]


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
    # both broken events and the repo-less one are now rejections; nothing is "outside"
    assert s["events_outside_repo_list"] == 0 and s["events_no_repo_id"] == 0
    assert s["events_rejected"] == {"empty payload": 2, "missing repo.id": 1}
    assert s["events_accepted"] == 3                         # includes the other repo's valid PR


def test_main_writes_records_and_summary(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    sample(raw)
    (tmp_path / "tier.txt").write_text(f"{IN_TIER}\n")
    out = tmp_path / "records"
    assert main([str(raw), "--out", str(out), "--repos", str(tmp_path / "tier.txt")]) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["repo_list"].endswith("tier.txt") and summary["events_accepted"] == 2
    prs = [json.loads(l) for l in (out / "pull_request.ndjson").read_text().splitlines()]
    assert [p["pr_key"] for p in prs] == ["10/5"]
