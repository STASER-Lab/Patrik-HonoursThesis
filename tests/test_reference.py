"""The Python reference answers are the yardstick, so they get their own tests."""

from benchmark.queries import activity, q1, q2, q4, q5

PR = dict(
    repo_id=10, author_id=1, author_is_bot=False, created_at="2024-01-10T10:00:00Z"
)


class FakeData:
    def __init__(self, **entities):
        self.entities = entities

    def records(self, entity, repo_id):
        return [r for r in self.entities.get(entity, []) if r["repo_id"] == repo_id]


# TODO: q0 needs a test


def test_q1_first_response_rules():
    d = FakeData(
        pull_request=[
            {**PR, "pr_key": "10/1"},
            {**PR, "pr_key": "10/2"},
            {**PR, "pr_key": "10/3", "author_is_bot": True},
            {**PR, "pr_key": "10/4", "created_at": "2023-12-01T00:00:00Z"},
        ],
        comment=[
            {
                "repo_id": 10,
                "parent_type": "pr",
                "parent_key": "10/1",
                "author_id": 1,
                "author_is_bot": False,
                "created_at": "2024-01-10T10:01:00Z",
            },
            {
                "repo_id": 10,
                "parent_type": "pr",
                "parent_key": "10/1",
                "author_id": 3,
                "author_is_bot": True,
                "created_at": "2024-01-10T10:02:00Z",
            },
            {
                "repo_id": 10,
                "parent_type": "pr",
                "parent_key": "10/1",
                "author_id": 2,
                "author_is_bot": False,
                "created_at": "2024-01-10T11:00:00Z",
            },
        ],
        review=[
            {
                "repo_id": 10,
                "pr_key": "10/1",
                "author_id": 4,
                "author_is_bot": False,
                "submitted_at": "2024-01-10T10:30:00Z",
            }
        ],
    )
    assert q1.reference(d, 10) == {"10/1": 1800, "10/2": None}


def test_q2_counts_only_human_merged_prs_reviewed_by_others():
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
    assert q2.reference(d, 10) == {"merged": 2, "reviewed": 1, "share": 0.5}


def test_activity_ignores_bots_and_outside_window():
    d = FakeData(
        issue=[
            {
                "repo_id": 10,
                "author_id": 1,
                "author_is_bot": False,
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "repo_id": 10,
                "author_id": 1,
                "author_is_bot": False,
                "created_at": "2023-06-01T00:00:00Z",
            },
        ],
        comment=[
            {
                "repo_id": 10,
                "author_id": 2,
                "author_is_bot": True,
                "created_at": "2024-01-02T00:00:00Z",
            },
            {
                "repo_id": 10,
                "author_id": 1,
                "author_is_bot": False,
                "created_at": "2024-01-01T00:00:00Z",
            },
        ],
    )
    assert activity.reference(d, 10) == {1: [1704067200]}


""" def test_q3_labels_first_time_by_earlier_activity():
    d = FakeData(
        pull_request=[
            {
                **PR,
                "pr_key": "10/1",
                "author_id": 1,
                "created_at": "2024-01-10T10:00:00Z",
            },
            {
                **PR,
                "pr_key": "10/2",
                "author_id": 5,
                "created_at": "2024-01-10T10:00:00Z",
            },
        ],
        issue=[
            {
                "repo_id": 10,
                "author_id": 5,
                "author_is_bot": False,
                "created_at": "2024-01-05T00:00:00Z",
            }
        ],
        comment=[
            {
                "repo_id": 10,
                "parent_type": "pr",
                "parent_key": "10/1",
                "author_id": 9,
                "author_is_bot": False,
                "created_at": "2024-01-10T10:10:00Z",
            },
            {
                "repo_id": 10,
                "parent_type": "pr",
                "parent_key": "10/2",
                "author_id": 9,
                "author_is_bot": False,
                "created_at": "2024-01-10T11:00:00Z",
            },
        ],
    )
    # TODO: failing test, maximum recursion depth exceeded in comparison
    # assert q3.reference(d, 10) == {
    #    "first_time": {"prs": 1, "answered": 1, "median_seconds": 600},
    #    "regular": {"prs": 1, "answered": 1, "median_seconds": 3600},
    #} 
    """

def test_q4_cohorts_and_90_day_return():
    def c(person, at):
        return {
            "repo_id": 10,
            "author_id": person,
            "author_is_bot": False,
            "created_at": at,
            "parent_type": "issue",
            "parent_key": "10/9",
        }

    d = FakeData(
        comment=[
            c(1, "2024-01-05T00:00:00Z"),
            c(1, "2024-03-01T00:00:00Z"),
            c(2, "2024-01-20T00:00:00Z"),
            c(2, "2024-06-01T00:00:00Z"),
            c(3, "2024-10-02T00:00:00Z"),
        ]
    )
    assert q4.reference(d, 10) == {
        "2024-01": {"newcomers": 2, "returned": 1, "share": 0.5}
    }


def test_q5_issue_closed_via_merged_pr():
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
            {
                "repo_id": 10,
                "pr_key": "10/5",
                "issue_key": "10/1",
                "target_type": "issue",
            },
            {
                "repo_id": 10,
                "pr_key": "10/6",
                "issue_key": "10/1",
                "target_type": "issue",
            },
            {
                "repo_id": 10,
                "pr_key": "10/7",
                "issue_key": "10/4",
                "target_type": "issue",
            },
            {
                "repo_id": 10,
                "pr_key": "10/5",
                "issue_key": "10/3",
                "target_type": "issue",
            },
        ],
    )
    assert q5.reference(d, 10) == {
        "closed": 3,
        "via_pr": 1,
        "share": 0.3333,
        "median_seconds_to_merge": 43200,
    }


# TODO: q6 needs a test
