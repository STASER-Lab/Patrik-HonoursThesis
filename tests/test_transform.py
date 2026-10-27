"""Tests for validation, folding, and closing-keyword extraction."""

import copy
import gzip
import json

import pytest

from ingest.transform.fold import Folder, is_bot_account
from ingest.transform.links import add_links, find_references
from ingest.transform.screen import Screen
from ingest.transform.validate import Validator, check

REPO = {"id": 10, "name": "org/proj"}
ALICE = {"id": 1, "login": "alice.r", "type": "User"}
BOB = {"id": 2, "login": "bob62", "type": "User"}
BOT = {"id": 3, "login": "dependabot[bot]", "type": "Bot"}


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


def _pr_with_body(number, body, eid):
    return ev(
        eid,
        "PullRequestEvent",
        "2024-01-10T10:00:00Z",
        {
            "action": "opened",
            "number": number,
            "pull_request": {**pr_obj(number=number), "body": body},
        },
    )


def ev(eid, t, created_at, payload, actor=ALICE):
    return {
        "id": str(eid),
        "type": t,
        "created_at": created_at,
        "actor": actor,
        "repo": REPO,
        "payload": payload,
    }


def pr_opened(eid=1):
    return ev(
        eid,
        "PullRequestEvent",
        "2024-01-10T10:00:00Z",
        {"action": "opened", "number": 5, "pull_request": pr_obj()},
    )


def pr_merged(eid=3):
    return ev(
        eid,
        "PullRequestEvent",
        "2024-01-10T12:00:00Z",
        {
            "action": "closed",
            "number": 5,
            "pull_request": pr_obj(
                state="closed",
                merged_at="2024-01-10T12:00:00Z",
                closed_at="2024-01-10T12:00:00Z",
            ),
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


def write_lines(path, lines):
    with gzip.open(path, "wt") as f:
        for line in lines:
            f.write(line + "\n")
    return path


def compact(event):
    return json.dumps(event, separators=(",", ":"))


def fold(*events):
    f = Folder()
    for e in events:
        error = check(e)
        assert error is None, error
        f.add(e)
    return f


# ----------------------------------------------------------------------------
# Test screen.py


def test_screen_passes_only_five_type_events(tmp_path):
    lookalike = {
        "id": "9",
        "type": "PushEvent",
        "payload": {"note": 'quoted "type":"IssuesEvent" here'},
    }
    path = write_lines(
        tmp_path / "2024-01-10-0.json.gz",
        [
            compact(pr_opened(eid=1)),
            compact({"id": "2", "type": "PushEvent"}),
            compact(lookalike),
            '{"type":"IssuesEvent", broken',
            '["type":"IssuesEvent"]',
            '[{"type":"IssuesEvent"}]',
        ],
    )
    screen = Screen()
    events = list(screen([path]))
    assert [e["id"] for e in events] == ["1"]
    assert screen.counts == {"passed": 1, "other_types": 2, "unparseable": 3}


def test_screen_reads_files_in_the_order_given(tmp_path):
    a = write_lines(tmp_path / "a.json.gz", [compact(pr_opened(eid=1))])
    b = write_lines(
        tmp_path / "b.json.gz", [compact(pr_opened(eid=2)), compact(pr_opened(eid=3))]
    )
    assert [e["id"] for e in Screen()([b, a])] == ["2", "3", "1"]


# ----------------------------------------------------------------------------
# Test validate.py


def test_empty_payload_rejected():
    assert check({**pr_opened(), "payload": {}}) == "empty payload"


def test_missing_field_rejected_with_path():
    e = pr_opened()
    del e["payload"]["pull_request"]["user"]
    assert check(e) == "missing payload.pull_request.user.id"


def test_bad_timestamp_rejected():
    e = pr_opened()
    e["created_at"] = "yesterday"
    assert check(e) == "bad timestamp created_at"


def test_duplicate_event_rejected():
    v = Validator()
    assert v(pr_opened()) and not v(pr_opened())
    assert v.rejected == {"duplicate event id": 1}


# ----------------------------------------------------------------------------
# Test fold.py


def test_pr_events_fold_into_latest_state():
    f = fold(pr_opened(), pr_merged())
    pr = f.records["pull_request"]["10/5"]
    assert pr["state"] == "closed" and pr["merged"] is True
    assert (
        pr["merged_at"] == "2024-01-10T12:00:00Z"
    )  # GitHub/GH Archive timestamps are always UTC with a Z
    assert f.counts()["pull_request"] == 1


def test_latest_wins_even_when_events_arrive_out_of_order():
    f = fold(pr_merged(), pr_opened())
    assert f.records["pull_request"]["10/5"]["merged"] is True


def test_issue_comment_on_pr_links_by_number():
    f = fold(pr_opened(), comment_on_pr())
    c = f.records["comment"][77]
    assert (
        c["parent_type"] == "pr"
        and c["parent_key"] == "10/5"
        and c["kind"] == "issue_comment"
    )
    assert f.counts()["issue"] == 0


def test_comment_alone_creates_parent_pr_from_snapshot():
    # A PR opened before 2024 whose only 2024 activity is a comment still gets a record
    f = fold(comment_on_pr())
    assert f.records["pull_request"]["10/5"]["author_id"] == ALICE["id"]


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
    f = fold(pr_opened(), e)
    r = f.records["review"][55]
    assert (
        r["state"] == "approved"
        and r["pr_key"] == "10/5"
        and r["author_id"] == BOB["id"]
    )


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
    f = fold(e)
    assert f.records["comment"][88]["kind"] == "review_comment"
    assert f.records["comment"][88]["parent_key"] == "10/5"


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
    renamed = copy.deepcopy(comment_on_pr(eid=9, at="2024-01-10T13:00:00Z", cid=78))
    renamed["payload"]["comment"]["user"] = {**BOB, "login": "bob-new"}
    renamed["actor"] = {**BOB, "login": "bob-new"}
    f = fold(comment_on_pr(), renamed)
    assert f.records["person"][BOB["id"]]["login"] == "bob-new"


# ----------------------------------------------------------------------------
# Test links.py


def test_keywords_and_forms():
    body = (
        "Fixes #12. Also closes: #13 and RESOLVED #14.\n"
        "See https://github.com/org/proj/issues/15 - fixed https://github.com/org/proj/issues/16\n"
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
    links = f.records["link"]
    assert {k: v["target_type"] for k, v in links.items()} == {
        "10/8->7": "issue",
        "10/8->5": "pr",
        "10/8->99": "unknown",
        "10/9->7": "issue",
    }
    assert stats["self_reference_skipped"] == 1 and stats["cross_repo_skipped"] == 1
    assert stats["duplicate_skipped"] == 1 and stats["links"] == 4


def test_latest_body_wins():
    f = Folder()
    f.add(_pr_with_body(8, "fixes #1", eid=1))
    edited = _pr_with_body(8, "fixes #2", eid=2)
    edited["created_at"] = "2024-01-10T11:00:00Z"
    f.add(edited)
    add_links(f)
    assert list(f.records["link"]) == ["10/8->2"]
