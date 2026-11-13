"""Transform step 4: fold events into one record per entity.

Every event touching an issue or PR carries a full snapshot of it, so a record
takes its fields from the latest event, whatever order events arrive in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bots import is_bot_account
from .validate import get

ENTITIES = (
    "repository",
    "person",
    "issue",
    "pull_request",
    "comment",
    "review",
    "link",
)

Version = tuple[str, int]  # (created_at, event id): the id breaks same-second ties


def key(repo_id: int, number: int) -> str:
    return f"{repo_id}/{number}"


@dataclass
class Folder:
    records: dict[str, dict[Any, dict]] = field(
        default_factory=lambda: {e: {} for e in ENTITIES}
    )
    versions: dict[tuple[str, Any], Version] = field(default_factory=dict)

    def _upsert(self, entity: str, k: Any, version: Version, fields: dict) -> dict:
        """Apply `fields` unless the record already holds a newer version"""
        vkey = (entity, k)
        rec = self.records[entity].setdefault(k, {})
        if version >= self.versions.get(vkey, ("", -1)):
            rec.update(fields)
            self.versions[vkey] = version
        return rec

    def _person(self, user: dict, version: Version) -> dict[str, Any]:
        pid = user["id"]
        is_bot = is_bot_account(user)
        self._upsert(
            "person",
            pid,
            version,
            {"person_id": pid, "login": user.get("login"), "is_bot": is_bot},
        )
        return {"author_id": pid, "author_is_bot": is_bot}

    def _repository(self, ev: dict, version: Version) -> int:
        rid = ev["repo"]["id"]
        rec = self._upsert(
            "repository", rid, version, {"repo_id": rid, "name": ev["repo"]["name"]}
        )
        # Only PR payloads reveal fork status, so a repository without PR events
        # stays None and is kept
        rec.setdefault("is_fork", None)
        rec["events"] = rec.get("events", 0) + 1
        return rid

    def _thread_base(self, rid: int, item: dict, version: Version) -> dict[str, Any]:
        return {
            "repo_id": rid,
            "number": item["number"],
            **self._person(item["user"], version),
            "title": item.get("title"),
            "body": item.get("body"),
            "state": item.get("state"),
            "created_at": item["created_at"],
            "closed_at": item.get("closed_at"),
        }

    def _issue_snapshot(self, rid: int, issue: dict, version: Version) -> str:
        k = key(rid, issue["number"])
        self._upsert(
            "issue",
            k,
            version,
            {"issue_key": k, **self._thread_base(rid, issue, version)},
        )
        return k

    def _pr_snapshot(self, rid: int, pr: dict, version: Version) -> str:
        if (fork := get(pr, "base.repo.fork")) is not None:
            self.records["repository"][rid]["is_fork"] = fork
        merged_at = pr.get("merged_at") or get(pr, "pull_request.merged_at")
        k = key(rid, pr["number"])
        self._upsert(
            "pull_request",
            k,
            version,
            {
                "pr_key": k,
                **self._thread_base(rid, pr, version),
                "merged_at": merged_at,
                "merged": merged_at is not None,
            },
        )
        return k

    def _comment(
        self,
        rid: int,
        c: dict,
        kind: str,
        parent_type: str,
        parent: str,
        version: Version,
    ) -> None:
        self.records["comment"][c["id"]] = {
            "comment_id": c["id"],
            "repo_id": rid,
            "kind": kind,
            "parent_type": parent_type,
            "parent_key": parent,
            **self._person(c["user"], version),
            "body": c.get("body"),
            "created_at": c["created_at"],
        }

    def add(self, ev: dict) -> None:
        t, pl = ev["type"], ev["payload"]
        version: Version = (ev["created_at"], int(ev["id"]))
        rid = self._repository(ev, version)
        self._person(ev["actor"], version)

        if t == "IssuesEvent":
            self._issue_snapshot(rid, pl["issue"], version)

        elif t == "PullRequestEvent":
            self._pr_snapshot(rid, pl["pull_request"], version)

        elif t == "IssueCommentEvent":
            issue = pl["issue"]
            # Comments on PRs arrive as IssueCommentEvent with issue.pull_request set
            if issue.get("pull_request"):
                parent_type, parent = "pr", self._pr_snapshot(rid, issue, version)
            else:
                parent_type, parent = "issue", self._issue_snapshot(rid, issue, version)
            self._comment(
                rid, pl["comment"], "issue_comment", parent_type, parent, version
            )

        elif t == "PullRequestReviewEvent":
            parent = self._pr_snapshot(rid, pl["pull_request"], version)
            r = pl["review"]
            # Reviews and comments are written once: GH Archive records no edits
            self.records["review"][r["id"]] = {
                "review_id": r["id"],
                "repo_id": rid,
                "pr_key": parent,
                **self._person(r["user"], version),
                "state": (r.get("state") or "").lower() or None,
                "body": r.get("body"),
                "submitted_at": r["submitted_at"],
            }

        elif t == "PullRequestReviewCommentEvent":
            parent = self._pr_snapshot(rid, pl["pull_request"], version)
            self._comment(rid, pl["comment"], "review_comment", "pr", parent, version)
