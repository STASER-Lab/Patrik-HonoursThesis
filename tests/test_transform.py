import gzip
import json

import pytest

from ingest.transform.bots import is_bot_account
from ingest.transform.build_records import main, run
from ingest.transform.fold import Folder
from ingest.transform.links import add_links, find_references
from ingest.transform.screen import Screen
from ingest.transform.validate import Validator, check

REPO = {"id": 10, "name": "org/proj"}
ALICE = {"id": 1, "login": "alice.r", "type": "User"}
BOB = {"id": 2, "login": "bob62", "type": "User"}
BOT = {"id": 3, "login": "dependabot[bot]", "type": "Bot"}
IN_TIER, OUTSIDE = 10, 99


def pr_obj(
    number=5, state="open", merged_at=None, closed_at=None, user=ALICE, fork=False
):
    return {
        "number": number,
        "id": 999,
        "user": user,
        "title": "Fix",
        "body": "b",
        "state": state,
        "created_at": "2024-01-10T10:00:00Z",
        "closed_at": closed_at,
        "merged_at": merged_at,
        "base": {"repo": {"id": REPO["id"], "fork": fork}},
    }


def ev(eid, t, created_at, payload, actor=ALICE):
    return {
        "id": str(eid),
        "type": t,
        "created_at": created_at,
        "actor": actor,
        "repo": REPO,
        "payload": payload,
    }


def _pr_with_body(number, body, eid, at="2024-01-10T10:00:00Z"):
    return ev(
        eid,
        "PullRequestEvent",
        at,
        {
            "action": "opened",
            "number": number,
            "pull_request": {**pr_obj(number=number), "body": body},
        },
    )


def pr_opened(eid=1):
    return ev(
        eid,
        "PullRequestEvent",
        "2024-01-10T10:00:00Z",
        {"action": "opened", "number": 5, "pull_request": pr_obj()},
    )


def pr_merged(eid=3):
    ts = "2024-01-10T12:00:00Z"
    return ev(
        eid,
        "PullRequestEvent",
        ts,
        {
            "action": "closed",
            "number": 5,
            "pull_request": pr_obj(state="closed", merged_at=ts, closed_at=ts),
        },
    )


def comment_on_pr(eid=2, user=BOB, at="2024-01-10T11:00:00Z", cid=77):
    issue_view = {
        "number": 5,
        "id": 12345,
        "user": ALICE,
        "title": "Fix",
        "body": "b",
        "state": "open",
        "created_at": "2024-01-10T10:00:00Z",
        "closed_at": None,
        "pull_request": {"url": "x", "merged_at": None},
    }
    return ev(
        eid,
        "IssueCommentEvent",
        at,
        {
            "action": "created",
            "issue": issue_view,
            "comment": {"id": cid, "user": user, "body": "LGTM", "created_at": at},
        },
        actor=user,
    )


def write_gz(path, items):
    with gzip.open(path, "wt") as f:
        for item in items:
            line = (
                item
                if isinstance(item, str)
                else json.dumps(item, separators=(",", ":"))
            )
            f.write(line + "\n")
    return path


def fold(*events):
    f = Folder()
    for e in events:
        assert check(e) is None
        f.add(e)
    return f


def test_screen_passes_only_five_type_events(tmp_path):
    lookalike = {
        "id": "9",
        "type": "PushEvent",
        "payload": {"note": 'quoted "type":"IssuesEvent" here'},
    }
    path = write_gz(
        tmp_path / "2024-01-10-0.json.gz",
        [
            pr_opened(eid=1),
            {"id": "2", "type": "PushEvent"},
            lookalike,
            '{"type":"IssuesEvent", broken',
            '["type":"IssuesEvent"]',
            '[{"type":"IssuesEvent"}]',
        ],
    )
    screen = Screen()
    assert [e["id"] for e in screen([path])] == ["1"]
    assert screen.counts == {"passed": 1, "other_types": 2, "unparseable": 3}


def test_screen_reads_files_in_the_order_given(tmp_path):
    a = write_gz(tmp_path / "a.json.gz", [pr_opened(eid=1)])
    b = write_gz(tmp_path / "b.json.gz", [pr_opened(eid=2), pr_opened(eid=3)])
    assert [e["id"] for e in Screen()([b, a])] == ["2", "3", "1"]


def test_validation_rejects_invalid_events():
    assert check({**pr_opened(), "payload": {}}) == "empty payload"
    assert (
        check({**pr_opened(), "created_at": "yesterday"}) == "bad timestamp created_at"
    )
    e = pr_opened()
    del e["payload"]["pull_request"]["user"]
    assert check(e) == "missing payload.pull_request.user.id"


def test_duplicate_event_rejected():
    v = Validator()
    assert v(pr_opened()) and not v(pr_opened())
    assert v.rejected == {"duplicate event id": 1}


def test_pr_events_fold_into_latest_state():
    f = fold(pr_opened(), pr_merged())
    pr = f.records["pull_request"]["10/5"]
    assert pr["state"] == "closed" and pr["merged"] is True
    assert pr["merged_at"] == "2024-01-10T12:00:00Z"
    assert len(f.records["pull_request"]) == 1


def test_latest_wins_even_when_events_arrive_out_of_order():
    assert (
        fold(pr_merged(), pr_opened()).records["pull_request"]["10/5"]["merged"] is True
    )


def test_issue_comment_on_pr_links_by_number():
    f = fold(pr_opened(), comment_on_pr())
    c = f.records["comment"][77]
    assert (c["parent_type"], c["parent_key"], c["kind"]) == (
        "pr",
        "10/5",
        "issue_comment",
    )
    assert not f.records["issue"]


def test_comment_alone_creates_parent_pr_from_snapshot():
    assert (
        fold(comment_on_pr()).records["pull_request"]["10/5"]["author_id"]
        == ALICE["id"]
    )


def test_issue_comment_on_issue():
    e = comment_on_pr()
    del e["payload"]["issue"]["pull_request"]
    f = fold(e)
    assert f.records["comment"][77]["parent_type"] == "issue"
    assert "10/5" in f.records["issue"] and not f.records["pull_request"]


def test_review_creates_review_and_updates_pr():
    e = ev(
        4,
        "PullRequestReviewEvent",
        "2024-01-10T11:30:00Z",
        {
            "action": "created",
            "pull_request": pr_obj(),
            "review": {
                "id": 55,
                "user": BOB,
                "state": "APPROVED",
                "body": "",
                "submitted_at": "2024-01-10T11:30:00Z",
            },
        },
        actor=BOB,
    )
    r = fold(pr_opened(), e).records["review"][55]
    assert (r["state"], r["pr_key"], r["author_id"]) == ("approved", "10/5", BOB["id"])


def test_review_comment_is_a_pr_comment():
    e = ev(
        6,
        "PullRequestReviewCommentEvent",
        "2024-01-10T11:40:00Z",
        {
            "action": "created",
            "pull_request": pr_obj(),
            "comment": {
                "id": 88,
                "user": BOB,
                "body": "nit",
                "created_at": "2024-01-10T11:40:00Z",
            },
        },
        actor=BOB,
    )
    c = fold(e).records["comment"][88]
    assert c["kind"] == "review_comment" and c["parent_key"] == "10/5"


def test_bot_flag():
    f = fold(comment_on_pr(user=BOT, cid=90))
    assert f.records["person"][BOT["id"]]["is_bot"] is True
    assert f.records["person"][ALICE["id"]]["is_bot"] is False


@pytest.mark.parametrize(
    ("account", "expected"),
    [
        ({"login": "some-app", "type": "Bot"}, True),
        ({"login": "some-app[bot]", "type": "User"}, True),
        ({"login": "dependabot", "type": "User"}, True),
        ({"login": "wingetbot", "type": "User"}, True),
        ({"login": "k8s-ci-robot", "type": "User"}, True),
        ({"login": "JuliaTagBot", "type": "User"}, True),
        ({"login": "kibanamachine", "type": "User"}, True),
        ({"login": "aws-aemilia-pdx", "type": "User"}, True),
        ({"login": "paleolimbot", "type": "User"}, False),
        ({"login": "RyanJTalbot", "type": "User"}, False),
        ({"login": "olgabot", "type": "Bot"}, True),
        ({"login": "botanist", "type": "User"}, False),
        ({"login": None}, False),
        (ALICE, False),
    ],
)
def test_is_bot_account(account, expected):
    assert is_bot_account(account) is expected


def test_fork_flag():
    e = pr_opened()
    e["payload"]["pull_request"]["base"]["repo"]["fork"] = True
    assert fold(e).records["repository"][10]["is_fork"] is True


def test_person_login_follows_latest_event():
    renamed = comment_on_pr(
        eid=9, user={**BOB, "login": "bob-new"}, at="2024-01-10T13:00:00Z", cid=78
    )
    f = fold(comment_on_pr(), renamed)
    assert f.records["person"][BOB["id"]]["login"] == "bob-new"


def test_keywords_and_forms():
    body = (
        "Fixes #12. Also closes: #13 and RESOLVED #14.\n"
        "See https://github.com/org/proj/issues/15 - "
        "fixed https://github.com/org/proj/issues/16\n"
        "fixes other/repo#17"
    )
    assert find_references(body) == [
        ("fix", None, 12),
        ("close", None, 13),
        ("resolve", None, 14),
        ("fix", "org/proj", 16),
        ("fix", "other/repo", 17),
    ]


def test_non_matches():
    assert find_references("prefix #1, unfixed #2, see #4, fixes, #5") == []
    assert find_references("Fixes #1, #2") == [("fix", None, 1)]
    assert find_references(None) == []


def test_add_links_types_targets_and_skips():
    issue_event = comment_on_pr(eid=50, cid=500)
    del issue_event["payload"]["issue"]["pull_request"]
    issue_event["payload"]["issue"]["number"] = 7
    f = Folder()
    for e in (
        issue_event,
        pr_opened(eid=1),
        _pr_with_body(
            8,
            "Fixes #7, fixes #5, fixes #99, fixes #8, fixes other/x#1, fixes #7",
            eid=2,
        ),
        _pr_with_body(9, "closes org/proj#7", eid=3),
    ):
        f.add(e)
    stats = add_links(f)
    assert stats["self_reference_skipped"] == 1 and stats["cross_repo_skipped"] == 1
    assert stats["duplicate_skipped"] == 1 and stats["links"] == 4


def test_latest_body_wins():
    f = Folder()
    f.add(_pr_with_body(8, "fixes #1", eid=1))
    f.add(_pr_with_body(8, "fixes #2", eid=2, at="2024-01-10T11:00:00Z"))
    add_links(f)
    assert list(f.records["link"]) == ["10/8->2"]


def _in_repo(event, repo_id):
    return {**event, "repo": {"id": repo_id, "name": f"org/r{repo_id}"}}


def _fork_pr(repo_id, eid):
    e = _in_repo(pr_opened(eid=eid), repo_id)
    e["payload"]["pull_request"] = pr_obj(fork=True)
    return e


def read(out, entity):
    return [
        json.loads(ln) for ln in (out / f"{entity}.ndjson").read_text().splitlines()
    ]


def test_tier_check_runs_before_validation(tmp_path):
    broken = {**pr_opened(eid=3), "payload": {}}
    files = [
        write_gz(
            tmp_path / "2024-01-10-0.json.gz",
            [
                pr_opened(eid=1),
                comment_on_pr(eid=2),
                broken,
                _in_repo({**broken, "id": "4"}, OUTSIDE),
                _in_repo(pr_opened(eid=5), OUTSIDE),
                {**pr_opened(eid=6), "repo": None},
                {"id": "7", "type": "PushEvent", "repo": {"id": IN_TIER}},
                '{"type":"IssuesEvent", not json',
            ],
        )
    ]
    out = tmp_path / "out"
    s = run(files, {IN_TIER}, out)
    assert s["events_accepted"] == 2
    assert s["events_rejected"] == {"empty payload": 1}
    assert s["events_outside_repo_list"] == 2
    assert s["events_no_repo_id"] == 1
    assert s["events_other_types"] == 1
    assert s["events_unparseable"] == 1
    assert [p["pr_key"] for p in read(out, "pull_request")] == ["10/5"]


def test_forks_are_dropped_and_events_counted(tmp_path):
    events = [
        pr_opened(eid=1),
        comment_on_pr(eid=2),
        _fork_pr(12, eid=3),
        _in_repo(comment_on_pr(eid=4, cid=79), 12),
    ]
    out = tmp_path / "out"
    s = run([write_gz(tmp_path / "a.json.gz", events)], None, out)
    assert [(r["repo_id"], r["events"]) for r in read(out, "repository")] == [
        (IN_TIER, 2)
    ]
    assert all(r["repo_id"] == IN_TIER for r in read(out, "comment"))
    assert s["forks_dropped"] == {"repos": 1, "events": 2}
    assert s["records"]["repository"] == 1


def test_bucket_count_does_not_change_the_records(tmp_path):
    alice_new = {"id": 1, "login": "alice-new", "type": "User"}
    renamed = comment_on_pr(eid=2, user=alice_new, at="2024-01-10T13:00:00Z")
    renamed["payload"]["issue"]["user"] = alice_new
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
