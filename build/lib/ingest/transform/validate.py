"""Transform step 3: reject malformed and duplicate events"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_COMMON = ["id", "created_at", "actor.id", "actor.login", "repo.id", "repo.name"]
_ISSUE = ["payload.issue.number", "payload.issue.user.id", "payload.issue.created_at"]
_PR = ["payload.pull_request.user.id", "payload.pull_request.created_at"]
_PR_REF = ["payload.pull_request.number", *_PR]
_COMMENT = [
    "payload.comment.id",
    "payload.comment.user.id",
    "payload.comment.created_at",
]

REQUIRED: dict[str, list[str]] = {
    "IssuesEvent": [*_COMMON, "payload.action", *_ISSUE],
    "PullRequestEvent": [*_COMMON, "payload.action", "payload.number", *_PR],
    "IssueCommentEvent": [*_COMMON, *_ISSUE, *_COMMENT],
    "PullRequestReviewEvent": [
        *_COMMON,
        *_PR_REF,
        "payload.review.id",
        "payload.review.user.id",
        "payload.review.submitted_at",
    ],
    "PullRequestReviewCommentEvent": [*_COMMON, *_PR_REF, *_COMMENT],
}


def get(obj: Any, dotted: str) -> Any:
    for key in dotted.split("."):
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


def check(event: dict) -> str | None:
    """Why `event` is unusable, or None. `event["type"]` must be a key of REQUIRED."""
    if not event.get("payload"):
        return "empty payload"
    for path in REQUIRED[event["type"]]:
        if (value := get(event, path)) is None:
            return f"missing {path}"
        if path.endswith(("created_at", "submitted_at")):
            # Exactly this format: timestamps are later compared as strings
            try:
                datetime.strptime(value, TS_FORMAT)
            except TypeError, ValueError:
                return f"bad timestamp {path}"
    return None


@dataclass
class Validator:
    """`check` plus duplicate detection. Every accepted id is held for the whole run."""

    seen_ids: set[str] = field(default_factory=set)
    rejected: Counter[str] = field(default_factory=Counter)
    accepted: int = 0

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
