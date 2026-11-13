"""Transform step 1: keep lines whose event type is one of the five studied"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

EVENT_TYPES = {
    "IssuesEvent",
    "PullRequestEvent",
    "IssueCommentEvent",
    "PullRequestReviewEvent",
    "PullRequestReviewCommentEvent",
}

# A byte search skips most lines before JSON parsing. It relies on GH Archive's
# compact JSON (`"type":"X"`, no spaces): reformatted input would be counted as
# other_types.
_TYPE_MARKERS = tuple(f'"type":"{t}"'.encode() for t in EVENT_TYPES)


@dataclass
class Screen:
    counts: Counter[str] = field(default_factory=Counter)

    def __call__(self, files: Iterable[Path]) -> Iterator[dict]:
        for path in files:
            with gzip.open(path, "rb") as f:
                for line in f:
                    if not any(m in line for m in _TYPE_MARKERS):
                        self.counts["other_types"] += 1
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if not isinstance(event, dict):
                        self.counts["unparseable"] += 1
                        continue
                    # A marker could match inside another field (e.g. comment body)
                    if event.get("type") not in EVENT_TYPES:
                        self.counts["other_types"] += 1
                        continue
                    self.counts["passed"] += 1
                    yield event
