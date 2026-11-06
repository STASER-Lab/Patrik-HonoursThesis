"""The Python reference answers are the yardstick, so they get their own tests."""

from benchmark.queries import q1

PR = dict(repo_id=10, author_id=1, author_is_bot=False, created_at="2024-01-10T10:00:00Z")


class FakeData:
    def __init__(self, **entities):
        self.entities = entities

    def records(self, entity, repo_id):
        return [r for r in self.entities.get(entity, []) if r["repo_id"] == repo_id]


def test_q1_first_response_rules():
    d = FakeData(
        pull_request=[
            {**PR, "pr_key": "10/1"},
            {**PR, "pr_key": "10/2"},
            {**PR, "pr_key": "10/3", "author_is_bot": True},
            {**PR, "pr_key": "10/4", "created_at": "2023-12-01T00:00:00Z"}],
        comment=[
            {"repo_id": 10, "parent_type": "pr", "parent_key": "10/1", "author_id": 1,
             "author_is_bot": False, "created_at": "2024-01-10T10:01:00Z"},
            {"repo_id": 10, "parent_type": "pr", "parent_key": "10/1", "author_id": 3,
             "author_is_bot": True, "created_at": "2024-01-10T10:02:00Z"},
            {"repo_id": 10, "parent_type": "pr", "parent_key": "10/1", "author_id": 2,
             "author_is_bot": False, "created_at": "2024-01-10T11:00:00Z"}],
        review=[{"repo_id": 10, "pr_key": "10/1", "author_id": 4, "author_is_bot": False,
                 "submitted_at": "2024-01-10T10:30:00Z"}])
    assert q1.reference(d, 10) == {"10/1": 1800, "10/2": None}
