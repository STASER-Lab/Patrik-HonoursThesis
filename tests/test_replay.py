import gzip
import json
from types import SimpleNamespace

import pytest

from benchmark.replay import reset, run
from benchmark.replay.derive import Deriver, State, hour_order
from benchmark.replay.derive import run as derive_run
from benchmark.replay.verify import compare
from ingest.load.mappings import LAYOUTS
from ingest.transform.build_records import run as build_records
from ingest.transform.fold import Folder
from ingest.transform.links import add_links

from .test_transform import ALICE, BOB, REPO, comment_on_pr, ev, pr_obj

T24 = "2024-01-10T10:00:00Z"
T25 = "2025-01-10T10:00:00Z"
# After the 2024 comment and review, whose PR snapshots carry the body "b"
LATE_2024 = "2024-01-10T12:00:00Z"


def pr_event(eid, at=T24, number=5, **kw):
    body = kw.pop("body", "b")
    pr = {**pr_obj(number=number, **kw), "body": body}
    payload = {"action": "opened", "number": number, "pull_request": pr}
    return ev(eid, "PullRequestEvent", at, payload)


def issue_event(eid, number, at=T25, state="open"):
    issue = {
        "number": number,
        "id": 500 + number,
        "user": ALICE,
        "title": "Bug",
        "body": "x",
        "state": state,
        "created_at": T24,
        "closed_at": None,
    }
    return ev(eid, "IssuesEvent", at, {"action": "opened", "issue": issue})


def review_event(eid, rid=88, at=T24):
    payload = {
        "action": "created",
        "pull_request": pr_obj(),
        "review": {
            "id": rid,
            "user": BOB,
            "state": "APPROVED",
            "body": "ok",
            "submitted_at": at,
        },
    }
    return ev(eid, "PullRequestReviewEvent", at, payload, actor=BOB)


def base_2024(*extra):
    """2024: PR #5 by Alice whose body closes #9 (unknown) and #7 (an issue), with
    a comment and a review by Bob"""
    f = Folder()
    for e in (
        issue_event(100, 7, at=T24),
        pr_event(1, at=LATE_2024, body="fixes #9, closes #7"),
        comment_on_pr(2, at="2024-01-10T11:00:00Z"),
        review_event(3, at="2024-01-10T11:30:00Z"),
        *extra,
    ):
        f.add(e)
    add_links(f)
    return {e: list(t.values()) for e, t in f.records.items()}


def writes(event, *extra):
    d = Deriver(State(base_2024(*extra)), LAYOUTS, "t")
    return {s: w["ops"] for s, w in d.writes(event).items()}


def targets(ops):
    return [
        (
            next(iter(o[0])),
            next(iter(o[0].values()))["_index"].split("-", 2)[2],
            next(iter(o[0].values()))["_id"],
        )
        for o in ops
    ]


def test_new_comment_writes_one_child_and_s3_rewrites_the_pr():
    event = comment_on_pr(10, at=T25, cid=78)
    event["payload"]["issue"]["body"] = "fixes #9, closes #7"  # snapshot unchanged
    w = writes(event)
    assert targets(w["s1"]) == [("index", "comment", "78")]
    assert targets(w["s4"]) == targets(w["s1"])
    assert targets(w["s2"]) == [("index", "comment", "78")]
    assert json.loads(w["s2"][0][1])["parent_author_id"] == ALICE["id"]
    assert targets(w["s3"]) == [("index", "pull_request", "10/5")]
    nested = json.loads(w["s3"][0][1])
    assert {c["comment_id"] for c in nested["comments"]} == {77, 78}


def test_non_copied_field_change_does_not_touch_s2_children():
    event = pr_event(12, at=T25, body="fixes #9, closes #7")
    event["payload"]["pull_request"]["title"] = "Better title"
    w = writes(event)
    for s in LAYOUTS:
        assert targets(w[s]) == [("index", "pull_request", "10/5")]


def test_copied_field_change_rewrites_every_s2_copy():
    w = writes(
        pr_event(
            13,
            at=T25,
            body="fixes #9, closes #7",
            state="closed",
            merged_at=T25,
            closed_at=T25,
        )
    )
    assert targets(w["s1"]) == [("index", "pull_request", "10/5")]
    assert set(targets(w["s2"])) == {
        ("index", "pull_request", "10/5"),
        ("index", "comment", "77"),
        ("index", "review", "88"),
        ("index", "link", "10/5->7"),
        ("index", "link", "10/5->9"),
    }
    assert targets(w["s2"])[0] == ("index", "pull_request", "10/5")  # parent first
    assert targets(w["s3"]) == [("index", "pull_request", "10/5")]


def test_body_change_adds_and_deletes_links():
    w = writes(pr_event(14, at=T25, body="resolves #7, fixes #8"))
    assert set(targets(w["s1"])) == {
        ("index", "pull_request", "10/5"),
        ("index", "link", "10/5->7"),  # keyword changed close -> resolve
        ("index", "link", "10/5->8"),
        ("delete", "link", "10/5->9"),
    }
    assert targets(w["s3"]) == [("index", "pull_request", "10/5")]
    assert {ln["number"] for ln in json.loads(w["s3"][0][1])["links"]} == {7, 8}


def test_issue_first_seen_retargets_links_to_it():
    w = writes(issue_event(15, 9))
    assert targets(w["s1"]) == [
        ("index", "issue", "10/9"),
        ("index", "link", "10/5->9"),
    ]
    assert json.loads(w["s1"][1][1])["target_type"] == "issue"
    s2_link = json.loads(w["s2"][1][1])
    assert s2_link["issue_state"] == "open" and s2_link["issue_author_id"] == 1
    assert targets(w["s3"]) == [
        ("index", "issue", "10/9"),
        ("index", "pull_request", "10/5"),
    ]


def test_issue_copied_change_rewrites_s2_links_to_it():
    w = writes(issue_event(16, 7, state="closed"))
    assert targets(w["s1"]) == [("index", "issue", "10/7")]
    assert targets(w["s2"]) == [
        ("index", "issue", "10/7"),
        ("index", "link", "10/5->7"),
    ]
    assert targets(w["s3"]) == [("index", "issue", "10/7")]


def test_rename_relinks_owner_repo_references():
    # The 2024 body names the repository by its later name, so the reference is
    # cross-repository until the rename arrives
    body = "fixes org/renamed#7"
    base = base_2024(pr_event(4, at="2024-01-10T13:00:00Z", body=body))
    assert base["link"] == []
    event = comment_on_pr(18, at=T25, cid=79)
    event["repo"] = {**REPO, "name": "org/renamed"}
    event["payload"]["issue"]["body"] = body
    d = Deriver(State(base), LAYOUTS, "t")
    w = {s: x["ops"] for s, x in d.writes(event).items()}
    assert set(targets(w["s1"])) == {
        ("index", "repository", "10"),
        ("index", "comment", "79"),
        ("index", "link", "10/5->7"),
    }
    assert targets(w["s3"])[-1] == ("index", "pull_request", "10/5")


def test_hours_are_ordered_numerically(tmp_path):
    names = ["2025-01-10-10.json.gz", "2025-01-10-2.json.gz", "2025-01-09-23.json.gz"]
    got = [p.name for p in hour_order(tmp_path / n for n in names)]
    assert got == [
        "2025-01-09-23.json.gz",
        "2025-01-10-2.json.gz",
        "2025-01-10-10.json.gz",
    ]


def _write_hour(path, events):
    with gzip.open(path, "wt") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")


@pytest.fixture
def replayed(tmp_path):
    """2024 and window hour files, the replay writes, and a combined batch build"""
    y24 = [
        issue_event(100, 7, at=T24),
        pr_event(1, at=LATE_2024, body="fixes #9, closes #7"),
        comment_on_pr(2, at="2024-01-10T11:00:00Z"),
        review_event(3, at="2024-01-10T11:30:00Z"),
    ]
    window = [
        comment_on_pr(20, at="2025-01-10T10:05:00Z", cid=90),
        pr_event(21, at="2025-01-10T10:06:00Z", body="resolves #7, fixes #8"),
        issue_event(22, 8, at="2025-01-10T10:07:00Z"),
        pr_event(
            23,
            at="2025-01-10T10:08:00Z",
            body="resolves #7, fixes #8",
            state="closed",
            merged_at=T25,
            closed_at=T25,
        ),
        issue_event(24, 7, at="2025-01-10T10:09:00Z", state="closed"),
        review_event(25, rid=91, at="2025-01-10T10:10:00Z"),
        pr_event(26, at="2025-01-10T10:11:00Z", number=6, body="fix #7"),
    ]
    raw24, raw25, both = (tmp_path / n for n in ("raw24", "raw25", "both"))
    for d in (raw24, raw25, both):
        d.mkdir()
    _write_hour(raw24 / "2024-01-10-10.json.gz", y24)
    _write_hour(both / "2024-01-10-10.json.gz", y24)
    _write_hour(raw25 / "2025-01-10-10.json.gz", window)
    _write_hour(both / "2025-01-10-10.json.gz", window)
    build_records(sorted(raw24.glob("*.gz")), None, tmp_path / "rec24")
    build_records(sorted(both.glob("*.gz")), None, tmp_path / "combined")
    summary = derive_run(
        list(raw25.glob("*.gz")), tmp_path / "rec24", tmp_path / "replay", "t"
    )
    return tmp_path, summary


@pytest.mark.parametrize("layout", LAYOUTS)
def test_replayed_writes_reproduce_the_combined_batch_build(replayed, layout):
    tmp, _ = replayed
    r = compare(
        layout,
        tmp / "rec24",
        tmp / "combined",
        tmp / "replay" / layout / "writes.ndjson",
        "t",
    )
    assert r["ok"], r


def test_summary_counts_every_event_and_expected_docs(replayed):
    _, summary = replayed
    assert summary["events"]["events"] == 7
    for s in LAYOUTS:
        assert summary[s]["events"] == 7
    assert summary["s1"]["deletes"] >= 1
    assert summary["s3"]["expected_counts"] == {
        "s3-t-repository": 1,
        "s3-t-person": 2,
        "s3-t-issue": 2,
        "s3-t-pull_request": 2,
    }
    # S3 rewrites whole PRs, so it writes more Lucene docs than S1 per event
    assert summary["s3"]["docs_per_event"] > summary["s1"]["docs_per_event"]


class FakeES:
    """Records calls. `docs` maps index name to its document count."""

    def __init__(self, docs):
        self.docs, self.calls = dict(docs), []
        call = lambda name: lambda **kw: self.calls.append((name, kw))  # noqa: E731
        self.indices = SimpleNamespace(
            exists=lambda index: index in self.docs,
            delete=self._delete,
            clone=self._clone,
            put_settings=call("put_settings"),
            refresh=call("refresh"),
        )
        self.cluster = SimpleNamespace(health=call("health"))

    def _delete(self, index):
        self.calls.append(("delete", {"index": index}))
        del self.docs[index]

    def _clone(self, index, target, settings):
        self.calls.append(("clone", {"index": index, "target": target, **settings}))
        self.docs[target] = self.docs[index]

    def count(self, index):
        return {"count": self.docs[index]}

    def bulk(self, operations, filter_path):
        self.calls.append(("bulk", {"n": len(operations)}))
        return {"errors": False}


def test_prepare_write_blocks_before_cloning_to_base():
    es = FakeES({"s1-t-issue": 3})
    reset.prepare(es, ["s1-t-issue"])
    assert [n for n, _ in es.calls[:2]] == ["put_settings", "clone"]
    assert es.calls[0][1]["settings"] == {"index.blocks.write": True}
    assert es.calls[1][1]["target"] == "base-s1-t-issue"


def test_reset_clones_back_with_no_replicas_refresh_off_and_writes_allowed():
    es = FakeES({"s1-t-issue": 5, "base-s1-t-issue": 3})
    reset.reset(es, ["s1-t-issue"])
    (_, deleted), (_, cloned) = es.calls[:2]
    assert deleted == {"index": "s1-t-issue"}
    assert cloned == {
        "index": "base-s1-t-issue",
        "target": "s1-t-issue",
        "index.number_of_replicas": 0,
        "index.refresh_interval": "-1",
        "index.blocks.write": None,
    }
    assert es.docs["s1-t-issue"] == 3


def _writes_file(path, ops_per_event):
    op = [{"index": {"_index": "s1-t-issue", "_id": "1"}}, '{"a": 1}']
    with open(path, "w") as f:
        for n in ops_per_event:
            f.write(json.dumps({"event": "e", "ops": [op] * n}) + "\n")
    return path


def test_batches_count_events_with_no_writes(tmp_path):
    path = _writes_file(tmp_path / "w.ndjson", [1, 0, 2, 0, 0])
    got = [(len(ops) // 2, n) for ops, n in run.batches(path, 2)]
    assert got == [(1, 2), (2, 2), (0, 1)]


def test_run_sends_batches_then_one_refresh_and_restores_refresh(tmp_path, monkeypatch):
    out = tmp_path / "replay" / "s1"
    out.mkdir(parents=True)
    _writes_file(out / "writes.ndjson", [1, 0, 2, 0, 0])
    summary = {
        "ops": 3,
        "docs": 3,
        "bytes": 30,
        "ops_per_event": 0.6,
        "docs_per_event": 0.6,
        "bytes_per_event": 6.0,
        "expected_counts": {"s1-t-issue": 3},
    }
    (out / "summary.json").write_text(json.dumps(summary))
    es = FakeES({"s1-t-issue": 3, "base-s1-t-issue": 3})
    monkeypatch.setattr(run, "client", lambda env_file: es)
    saved = {}
    monkeypatch.setattr(run, "save_result", lambda n, es, d: saved.update(d) or "x")
    argv = [
        "--layout",
        "s1",
        "--tier",
        "t",
        "--writes",
        str(tmp_path / "replay"),
        "--batch-events",
        "2",
    ]
    assert run.main(argv) == 0
    steps = [n for n, _ in es.calls]
    assert steps == ["bulk", "bulk", "refresh", "put_settings"]  # empty batch skipped
    assert es.calls[-1][1]["settings"] == {"index": {"refresh_interval": None}}
    assert saved["events"] == 5 and saved["requests"] == 2
    assert 0 <= saved["refresh_seconds"] <= saved["seconds"]
