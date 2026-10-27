"""Transform step 1: screen raw GH Archive lines"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

EVENT_TYPES = frozenset(
    {
        "IssuesEvent",
        "PullRequestEvent",
        "IssueCommentEvent",
        "PullRequestReviewEvent",
        "PullRequestReviewCommentEvent",
    }
)

# Pre-filter checking bytes first
_TYPE_MARKERS = tuple(f'"type":"{t}"'.encode() for t in EVENT_TYPES)


class Screen:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def __call__(self, files: Iterable[Path]) -> Iterator[dict]:
        for path in files:
            with gzip.open(path, "rb") as f:
                for line in f:
                    if not any(m in line for m in _TYPE_MARKERS):
                        self.counts["other_types"] += 1
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        self.counts["unparseable"] += 1
                        continue
                    if not isinstance(event, dict):
                        self.counts["unparseable"] += 1
                        continue
                    if event.get("type") not in EVENT_TYPES:
                        self.counts["other_types"] += (
                            1  # passed the byte check, wrong type
                        )
                        continue
                    self.counts["passed"] += 1
                    yield event
