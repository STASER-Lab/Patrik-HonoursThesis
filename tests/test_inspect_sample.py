import gzip
import json

from ingest.extract import inspect_sample as ins


def write_sample(path, events):
    with gzip.open(path, "wt") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_get_path_distinguishes_missing_from_null():
    obj = {"a": {"b": None}}
    assert ins.get_path(obj, "a.b") is None
    assert ins.get_path(obj, "a.c") is ins.MISSING
    assert ins.get_path(obj, "a.b.c") is ins.MISSING


def test_counts_types_fields_and_pr_comments(tmp_path):
    events = [
        {
            "type": "PullRequestEvent",
            "actor": {"login": "dependabot[bot]"},
            "payload": {"action": "closed", "pull_request": {"merged_at": None}},
        },
        {
            "type": "IssueCommentEvent",
            "actor": {"login": "alice"},
            "payload": {"action": "created", "issue": {"pull_request": {"url": "x"}}},
        },
        {
            "type": "IssueCommentEvent",
            "actor": {"login": "bob"},
            "payload": {"action": "created", "issue": {}},
        },
        {"type": "PushEvent"},
    ]
    write_sample(tmp_path / "2024-01-10-0.json.gz", events)
    s = ins.Stats()
    for line in ins.iter_lines([tmp_path / "2024-01-10-0.json.gz"]):
        s.add(line)

    assert s.all_events == 4
    assert s.count["PullRequestEvent"] == 1 and s.count["IssueCommentEvent"] == 2
    assert s.present["PullRequestEvent"]["payload.pull_request.merged_at"] == 1
    assert s.non_null["PullRequestEvent"]["payload.pull_request.merged_at"] == 0
    assert s.bot_login["PullRequestEvent"] == 1
    assert s.issue_comments_on_prs == 1
    assert "PullRequestEvent" in ins.report(s)


def test_main_fails_on_empty_folder(tmp_path):
    assert ins.main([str(tmp_path)]) == 1


def test_missing_action_is_labelled(tmp_path):
    write_sample(tmp_path / "x.json.gz", [{"type": "IssueCommentEvent", "payload": {}}])
    s = ins.Stats()
    for line in ins.iter_lines([tmp_path / "x.json.gz"]):
        s.add(line)
    assert s.actions["IssueCommentEvent"] == {"(missing)": 1}
