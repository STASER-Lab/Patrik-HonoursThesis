# GH Archive 2024: data profile

Source: BigQuery sandbox, public `githubarchive` dataset, queried 2026-10-18.
Queries: `ingest/sql/repository_ranking_2024.sql`, `volume_estimate_2024.sql`, `ranking_shape_2024.sql`.
Scope: the five event types (Issues, PullRequest, IssueComment, PullRequestReview, PullRequestReviewComment).

## Volume (12 sample Wednesdays, one per month; payload bytes only)

| Type | Sample events | Sample GB | Avg KB/event | Naive 2024 TB |
| --- | ---: | ---: | ---: | ---: |
| PullRequestEvent | 4,104,102 | 75.51 | 18.4 | 2.303 |
| PullRequestReviewEvent | 1,525,396 | 30.13 | 19.8 | 0.919 |
| IssueCommentEvent | 2,682,559 | 24.23 | 9.0 | 0.739 |
| PullRequestReviewCommentEvent | 957,133 | 20.66 | 21.6 | 0.630 |
| IssuesEvent | 1,684,721 | 11.69 | 6.9 | 0.357 |
| Total | 10,953,911 | 162.22 | 14.8 | 4.95 |

Weekday bias check: the sample implies 334M events for the year, but the full-year count is 283.9M (+18%).
Corrected estimate: 283.9M events × 14.8 KB ≈ 4.2 TB of raw payload. The "> 1 TB" assumption holds comfortably.

## Repository distribution (full year)

| Measure | Value |
| --- | ---: |
| Repositories with activity | 7,724,086 |
| Events | 283,880,836 |
| Median events per repository | 3 |
| p90 / p99 / p99.9 | 36 / 436 / 3,314 |
| Largest repository | 747,515 (microsoft/winget-pkgs) |
| Repositories with exactly 1 event | 1,465,190 (19%) |
| ≥ 100 events / ≥ 10,000 events | 331,605 / 2,136 |
| Renamed during 2024 (`name_count > 1`) | 128,476 (1.7%) |
| Share of events in top 1% of repositories | 60.0% |
| Share of events in top 0.1% | 35.8% |

## Tier sizing (at 14.8 KB per event, raw payload)

| Tier | ≈ Events | 10% single-repository cap |
| --- | ---: | ---: |
| 10 GB | 675k | 68k events |
| 100 GB | 6.75M | 675k events |
| 1 TB | 67.5M (≈24% of 2024) | 6.75M events |

The two largest repositories (747k, 730k events) exceed the 100 GB cap, so they enter at 1 TB at the earliest.

## Population filter comparison (see D-004)

| Rule | Repos | Events | Share of events | p50 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| a: no filter | 7,724,086 | 283,880,836 | 1.000 | 3 | 426 |
| b: actors ≥ 2 | 2,777,996 | 231,341,415 | 0.815 | 9 | 1,047 |
| c: actors ≥ 3 | 1,132,039 | 197,556,939 | 0.696 | 28 | 2,155 |
| d: actors ≥ 5 | 477,789 | 161,577,519 | 0.569 | 64 | 4,288 |
| e: actors ≥ 3, top account ≤ 0.8 | 1,078,561 | 186,750,812 | 0.658 | 26 | 2,178 |
| f: actors ≥ 3, top account ≤ 0.5 | 661,508 | 137,777,929 | 0.485 | 22 | 3,055 |
| g: e + events/actor ≤ 1000 | 1,078,278 | 181,692,189 | 0.640 | 26 | 2,188 |
| h: e + events/actor ≤ 500 | 1,077,427 | 177,918,692 | 0.627 | 26 | 2,037 |
