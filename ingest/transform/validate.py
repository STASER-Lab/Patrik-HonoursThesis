"""Transform step 3: keep the five event types and reject malformed events."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_COMMON = ["id", "created_at", "actor.id", "actor.login", "repo.id", "repo.name"]

REQUIRED: dict[str, list[str]] = {
    "IssuesEvent": [
        "payload.action",
        "payload.issue.number",
        "payload.issue.user.id",
        "payload.issue.created_at",
    ],
    "PullRequestEvent": [
        "payload.action",
        "payload.number",
        "payload.pull_request.user.id",
        "payload.pull_request.created_at",
    ],
    "IssueCommentEvent": [
        "payload.issue.number",
        "payload.issue.user.id",
        "payload.issue.created_at",
        "payload.comment.id",
        "payload.comment.user.id",
        "payload.comment.created_at",
    ],
    "PullRequestReviewEvent": [
        "payload.pull_request.number",
        "payload.pull_request.user.id",
        "payload.pull_request.created_at",
        "payload.review.id",
        "payload.review.user.id",
        "payload.review.submitted_at",
    ],
    "PullRequestReviewCommentEvent": [
        "payload.pull_request.number",
        "payload.pull_request.user.id",
        "payload.pull_request.created_at",
        "payload.comment.id",
        "payload.comment.user.id",
        "payload.comment.created_at",
    ],
}

_MISSING = object()


def get(obj: Any, dotted: str, default: Any = None) -> Any:
    for key in dotted.split("."):
        if not isinstance(obj, dict) or key not in obj:
            return default
        obj = obj[key]
    return obj


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, TS_FORMAT)


def check(event: dict) -> str | None:
    t = event.get("type")
    if not event.get("payload"):
        return "empty payload"
    for path in _COMMON + REQUIRED[t]:
        value = get(event, path, _MISSING)
        if value is _MISSING or value is None:
            return f"missing {path}"
        if path.endswith(("created_at", "submitted_at")):
            try:
                parse_ts(value)
            except TypeError, ValueError:
                return f"bad timestamp {path}"
    return None


class Validator:
    """Applies `check` plus duplicate detection. Counts every rejection reason."""

    def __init__(self) -> None:
        self.seen_ids: set[str] = set()
        self.rejected: Counter[str] = Counter()
        self.accepted = 0

    def __call__(self, event: dict) -> bool:
        reason = check(event)
        if reason is None and event["id"] in self.seen_ids:
            reason = "duplicate event id"
        if reason:
            self.rejected[reason] += 1
            return False
        self.seen_ids.add(event["id"])
        self.accepted += 1
        return True
