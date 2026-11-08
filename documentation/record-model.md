# Record model

The ETL folds GH Archive events into entity records. Every strategy (S1 to S4) and every
Python reference answer is built from these same records. Field names below are the
contract.

## Keys

| Entity | Key | Example | Why |
| --- | --- | --- | --- |
| Repository | `repo_id` = GitHub `repo.id` | `12345` | Survives renames (1.7% of repos renamed in 2024) |
| Person | `person_id` = GitHub `actor.id` / `user.id` | `67890` | Logins can change |
| Issue | `issue_key` = `"{repo_id}/{number}"` | `12345/42` | Comments reference their parent by number |
| Pull request | `pr_key` = `"{repo_id}/{number}"` | `12345/43` | A PR's issue-view `id` differs from `pull_request.id`. Only the number links them |
| Comment | `comment_id` = GitHub comment id | `987654` | Globally unique, never reused |
| Review | `review_id` = GitHub review id | `555` | Globally unique |
| Link | `link_key` = `"{pr_key}->{number}"` | `12345/43->42` | One record per PR and target. Re-extraction gives the same key |

Keys are fixed by the data, so loading twice overwrites instead of duplicating.
Issues and PRs share one number sequence per repository, so `issue_key` and `pr_key` never collide.

## Records

**repository**: `repo_id`, `name` (latest seen), `is_fork` (from PR `base.repo.fork`; `null` if the repo has no PR events)

**person**: `person_id`, `login` (latest seen), `is_bot` (same rule as `author_is_bot`, from the latest event)

**issue**: `issue_key`, `repo_id`, `number`, `author_id`, `author_is_bot`, `title`, `body`, `state`, `created_at`, `closed_at`

**pull_request**: `pr_key`, `repo_id`, `number`, `author_id`, `author_is_bot`, `title`, `body`, `state`, `created_at`, `closed_at`, `merged_at`, `merged` (= `merged_at` is not null)

**comment**: `comment_id`, `repo_id`, `kind` (`issue_comment` | `review_comment`), `parent_type` (`issue` | `pr`), `parent_key`, `author_id`, `author_is_bot`, `body`, `created_at`

**review**: `review_id`, `repo_id`, `pr_key`, `author_id`, `author_is_bot`, `state` (`approved` | `changes_requested` | `commented` | `dismissed`), `body`, `submitted_at`

**link**: `link_key`, `repo_id`, `pr_key`, `issue_key` (`"{repo_id}/{number}"`), `number`, `keyword` (`close` | `fix` | `resolve`), `target_type` (`issue` | `pr` | `unknown`)

`author_is_bot` is stored on every authored record. It is set from the author as seen in that event
(`is_bot_account` in `ingest/transform/bots.py`). Checks run in order, and the first match decides:

1. Bot if GitHub reports its type as `Bot` (`user.type`) or its login ends with `[bot]` (GitHub Apps).
2. Bot if its login is on the curated list (`CURATED_BOT_LOGINS`) or starts with a curated prefix
   (`CURATED_BOT_PREFIXES`, e.g. `aws-aemilia-`).
3. Human if its login is a known person whose login ends in "bot" (`KNOWN_HUMAN_LOGINS`, and logins
   ending in `talbot`).
4. Bot if its login ends in `bot` (this includes `robot`), the name rule of Dey et al. (MSR 2020).
5. Otherwise human.

Bots that post through a person's own account (for example status-page or mirror tools using a
personal token) are still counted as humans.

## Folding rules

1. **Snapshots:** Every event that touches an issue or PR carries a full snapshot of it. Snapshot sources by event type:
   - IssuesEvent → `payload.issue`
   - IssueCommentEvent → `payload.issue` (an issue, or a PR's issue view when `issue.pull_request` is set)
   - PullRequestEvent → `payload.pull_request`
   - PullRequestReviewEvent → `payload.pull_request`
   - PullRequestReviewCommentEvent → `payload.pull_request`
2. **Latest wins:** A parent record takes its fields from the snapshot of the latest event (`created_at`, ties broken by event `id`).
3. **Comments and reviews are append-only:** One record per `created` event. GH Archive has no edit or delete events for these.
4. **PR-ness:** A number is a PR if any event says so (`PullRequest*Event`, or `issue.pull_request` set). An issue comment on a PR gets `parent_type = pr`.
5. **Pre-window entities:** A PR opened in 2023 but active in 2024 is kept, with its real `created_at`. Per-month queries filter by date anyway.
6. **Links:** After folding, each PR's latest body is scanned for closing keywords (`ingest/transform/links.py`).
   Links are therefore derived from text, not recorded events: editing a PR body changes them.
