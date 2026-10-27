"""Reads and reports onGH Archvive downloaded *.json.gz files

  * event count and raw (uncompressed) JSON bytes, plus a share of all events
  * `payload.action` breakdown (opened / closed / created ...)
  * bot signals and the share of issue comments that are actually on PRs
  * a naive extrapolation of raw bytes to all of 2024 (8,784 hours)

This is not part of the pipeline. It is a tool to verify data source quality.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

EVENT_TYPES = (
    "IssuesEvent",
    "PullRequestEvent",
    "IssueCommentEvent",
    "PullRequestReviewEvent",
    "PullRequestReviewCommentEvent",
)

COMMON = [
    "id",
    "created_at",
    "actor.id",
    "actor.login",
    "repo.id",
    "repo.name",
    "payload.action",
]

REQUIRED: dict[str, list[str]] = {
    "IssuesEvent": COMMON
    + [
        "payload.issue.id",
        "payload.issue.number",
        "payload.issue.title",
        "payload.issue.body",
        "payload.issue.user.login",
        "payload.issue.user.type",
        "payload.issue.created_at",
        "payload.issue.closed_at",
        "payload.issue.state",
    ],
    "PullRequestEvent": COMMON
    + [
        "payload.number",
        "payload.pull_request.id",
        "payload.pull_request.user.login",
        "payload.pull_request.user.type",
        "payload.pull_request.created_at",
        "payload.pull_request.closed_at",
        "payload.pull_request.merged",
        "payload.pull_request.merged_at",
        "payload.pull_request.state",
    ],
    "IssueCommentEvent": COMMON
    + [
        "payload.issue.number",
        "payload.issue.pull_request",
        "payload.issue.user.login",
        "payload.comment.id",
        "payload.comment.user.login",
        "payload.comment.user.type",
        "payload.comment.created_at",
        "payload.comment.body",
    ],
    "PullRequestReviewEvent": COMMON
    + [
        "payload.pull_request.number",
        "payload.pull_request.user.login",
        "payload.review.id",
        "payload.review.user.login",
        "payload.review.user.type",
        "payload.review.state",
        "payload.review.submitted_at",
    ],
    "PullRequestReviewCommentEvent": COMMON
    + [
        "payload.pull_request.number",
        "payload.pull_request.user.login",
        "payload.comment.id",
        "payload.comment.user.login",
        "payload.comment.user.type",
        "payload.comment.created_at",
    ],
}

HOURS_IN_2024 = 366 * 24
MISSING = object()


def get_path(obj: Any, dotted: str) -> Any:
    for key in dotted.split("."):
        if not isinstance(obj, dict) or key not in obj:
            return MISSING
        obj = obj[key]
    return obj


def iter_lines(files: Iterable[Path]) -> Iterable[bytes]:
    for path in files:
        with gzip.open(path, "rb") as f:
            yield from f


class Stats:
    def __init__(self) -> None:
        self.files = 0
        self.all_events = 0
        self.all_bytes = 0
        self.bad_lines = 0
        self.count: Counter[str] = Counter()
        self.bytes: Counter[str] = Counter()
        self.actions: dict[str, Counter[str]] = defaultdict(Counter)
        self.present: dict[str, Counter[str]] = defaultdict(Counter)
        self.non_null: dict[str, Counter[str]] = defaultdict(Counter)
        self.bot_login = Counter()
        self.issue_comments_on_prs = 0

    def add(self, line: bytes) -> None:
        self.all_events += 1
        self.all_bytes += len(line)
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            self.bad_lines += 1
            return
        t = ev.get("type")
        if t not in REQUIRED:
            return
        self.count[t] += 1
        self.bytes[t] += len(line)
        action = get_path(ev, "payload.action")
        self.actions[t]["(missing)" if action is MISSING else str(action)] += 1
        for field in REQUIRED[t]:
            v = get_path(ev, field)
            if v is not MISSING:
                self.present[t][field] += 1
                if v is not None:
                    self.non_null[t][field] += 1
        if str(get_path(ev, "actor.login")).endswith(
            "[bot]"
        ):
            self.bot_login[t] += 1
        if t == "IssueCommentEvent" and get_path(
            ev, "payload.issue.pull_request"
        ) not in (MISSING, None):
            self.issue_comments_on_prs += 1


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f}%" if b else "  n/a"


def report(s: Stats) -> str:
    out = [
        "# GH Archive sample report\n",
        f"Files: {s.files} hourly files. All events: {s.all_events:,} "
        f"({s.all_bytes / 1e9:.2f} GB raw JSON). Unparseable lines: {s.bad_lines}\n",
        "## Volume of the five event types\n",
        "| Type | Events | Share of all events | Raw GB | Avg KB/event | Bot actors |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    five_bytes = 0
    for t in EVENT_TYPES:
        n, b = s.count[t], s.bytes[t]
        five_bytes += b
        out.append(
            f"| {t} | {n:,} | {pct(n, s.all_events)} | {b / 1e9:.3f} | "
            f"{(b / n / 1e3) if n else 0:.1f} | {pct(s.bot_login[t], n)} |"
        )
    out.append(
        f"\nFive types total: {five_bytes / 1e9:.2f} GB raw JSON in {s.files} hours."
    )
    if s.files:
        est = five_bytes / s.files * HOURS_IN_2024 / 1e12
        out.append(
            f"Naive extrapolation to 2024 ({HOURS_IN_2024} hours): "
            f"**~{est:.2f} TB** raw JSON. "
            "Activity varies by season and weekday, "
            "so sample days spread across the year."
        )
    n_ic = s.count["IssueCommentEvent"]
    out.append(
        f"\nIssue comments that are on PRs (`payload.issue.pull_request` set): "
        f"{s.issue_comments_on_prs:,} of {n_ic:,} "
        f"({pct(s.issue_comments_on_prs, n_ic).strip()})\n"
    )

    for t in EVENT_TYPES:
        n = s.count[t]
        out.append(f"## {t} ({n:,} events)\n")
        acts = ", ".join(f"`{a}` {c:,}" for a, c in s.actions[t].most_common())
        out.append(f"Actions: {acts or 'none'}\n")
        out.append("| Field | Key present | Non-null |")
        out.append("| --- | ---: | ---: |")
        for field in REQUIRED[t]:
            out.append(
                f"| `{field}` "
                f"| {pct(s.present[t][field], n)} | {pct(s.non_null[t][field], n)} |"
            )
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder", type=Path, help="folder of GH Archive *.json.gz files")
    p.add_argument("--report", type=Path, help="also write the Markdown report here")
    args = p.parse_args(argv)

    files = sorted(args.folder.glob("*.json.gz"))
    if not files:
        print(f"No *.json.gz files in {args.folder}", file=sys.stderr)
        return 1
    s = Stats()
    s.files = len(files)
    for line in iter_lines(files):
        s.add(line)
    text = report(s)
    print(text)
    if args.report:
        args.report.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
