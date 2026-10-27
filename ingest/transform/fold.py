"""Transform step 4: fold validated events into entity records."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

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

CURATED_BOT_LOGINS: frozenset[str] = frozenset(
    {
        # Dependencies
        "dependabot",
        "dependabot-preview",
        "renovate",
        "renovate-bot",
        "pyup-bot",
        "greenkeeper",
        # CI
        "travis",
        "travis-ci",
        "circleci",
        "appveyor",
        "azure-pipelines",
        "buildkite-bot",
        "drone-io",
        "jenkins-bot",
        # Code
        "codecov",
        "codecov-io",
        "sonarcloud",
        "snyk-bot",
        "whitesource-bolt-for-github",
        "deepsource-autofix",
        "github-advanced-security",
        # Release
        "semantic-release-bot",
        "release-drafter",
        "changeset-bot",
        "github-actions",
        # Documentation, maintenance
        "allcontributors",
        "all-contributors",
        "backportbot",
        "bors",
        "homu",
        "probot",
        "stale",
        "mergify",
        "kodiakhq",
        # Other
        "everypoliticianbot",
        "depfu",
        "scala-steward",
        "imgbot",
        "docker-library-bot",
        "siteleaf",
        "yoshi-automation",
        "yoshi-code-bot",
    }
)

Version = tuple[int, int]  # (event created_at, event id)


def key(repo_id: int, number: int) -> str:
    return f"{repo_id}/{number}"


def is_bot_account(user: dict) -> bool:
    login = str(user.get("login") or "").strip().casefold()
    account_type = str(user.get("type") or "").strip().casefold()
    return (
        account_type == "bot" or login.endswith("[bot]") or login in CURATED_BOT_LOGINS
    )


class Folder:
    def __init__(self) -> None:
        self.records: dict[str, dict[Any, dict]] = {e: {} for e in ENTITIES}
        self._versions: dict[tuple[str, Any], Version] = {}

    def _upsert(self, entity: str, k: Any, version: Version, fields: dict) -> None:
        """Replace `fields` on the record if this event is newer"""
        vkey = (entity, k)
        rec = self.records[entity].setdefault(k, {})
        if vkey not in self._versions or version >= self._versions[vkey]:
            rec.update(fields)
            self._versions[vkey] = version

    def _person(self, user: dict, version: Version) -> int:
        pid = user["id"]
        self._upsert(
            "person",
            pid,
            version,
            {
                "person_id": pid,
                "login": user.get("login"),
                "is_bot": is_bot_account(user),
            },
        )
        return pid

    def _repository(self, ev: dict, version: Version) -> int:
        rid = ev["repo"]["id"]
        self._upsert(
            "repository", rid, version, {"repo_id": rid, "name": ev["repo"]["name"]}
        )
        rec = self.records["repository"][rid]
        rec.setdefault("is_fork", None)
        return rid

    def _issue_snapshot(self, rid: int, issue: dict, version: Version) -> str:
        k = key(rid, issue["number"])
        self._upsert(
            "issue",
            k,
            version,
            {
                "issue_key": k,
                "repo_id": rid,
                "number": issue["number"],
                "author_id": self._person(issue["user"], version),
                "author_is_bot": is_bot_account(issue["user"]),
                "title": issue.get("title"),
                "body": issue.get("body"),
                "state": issue.get("state"),
                "created_at": issue["created_at"],
                "closed_at": issue.get("closed_at"),
            },
        )
        return k

    def _pr_snapshot(self, rid: int, pr: dict, version: Version, merged_at: Any) -> str:
        k = key(rid, pr["number"])
        self._upsert(
            "pull_request",
            k,
            version,
            {
                "pr_key": k,
                "repo_id": rid,
                "number": pr["number"],
                "author_id": self._person(pr["user"], version),
                "author_is_bot": is_bot_account(pr["user"]),
                "title": pr.get("title"),
                "body": pr.get("body"),
                "state": pr.get("state"),
                "created_at": pr["created_at"],
                "closed_at": pr.get("closed_at"),
                "merged_at": merged_at,
                "merged": merged_at is not None,
            },
        )
        return k

    def _pr_from_pull_request(self, ev: dict, rid: int, version: Version) -> str:
        pr = ev["payload"]["pull_request"]
        fork = get(pr, "base.repo.fork")
        if fork is not None:
            self.records["repository"][rid]["is_fork"] = fork
        return self._pr_snapshot(rid, pr, version, pr.get("merged_at"))

    def add(self, ev: dict) -> None:
        t, pl = ev["type"], ev["payload"]
        version: Version = (ev["created_at"], int(ev["id"]))
        rid = self._repository(ev, version)
        self._person(ev["actor"], version)

        if t == "IssuesEvent":
            self._issue_snapshot(rid, pl["issue"], version)

        elif t == "PullRequestEvent":
            self._pr_from_pull_request(ev, rid, version)

        elif t == "IssueCommentEvent":
            issue = pl["issue"]
            if issue.get("pull_request"):
                parent_type = "pr"
                parent = self._pr_snapshot(
                    rid, issue, version, get(issue, "pull_request.merged_at")
                )
            else:
                parent_type = "issue"
                parent = self._issue_snapshot(rid, issue, version)
            self._comment(
                rid, pl["comment"], "issue_comment", parent_type, parent, version
            )

        elif t == "PullRequestReviewEvent":
            parent = self._pr_from_pull_request(ev, rid, version)
            r = pl["review"]
            self.records["review"][r["id"]] = {
                "review_id": r["id"],
                "repo_id": rid,
                "pr_key": parent,
                "author_id": self._person(r["user"], version),
                "author_is_bot": is_bot_account(r["user"]),
                "state": str(r.get("state", "")).lower() or None,
                "body": r.get("body"),
                "submitted_at": r["submitted_at"],
            }

        elif t == "PullRequestReviewCommentEvent":
            parent = self._pr_from_pull_request(ev, rid, version)
            self._comment(rid, pl["comment"], "review_comment", "pr", parent, version)

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
            "author_id": self._person(c["user"], version),
            "author_is_bot": is_bot_account(c["user"]),
            "body": c.get("body"),
            "created_at": c["created_at"],
        }

    def iter_records(self, entity: str) -> Iterator[dict]:
        yield from self.records[entity].values()

    def counts(self) -> dict[str, int]:
        return {e: len(self.records[e]) for e in ENTITIES}
