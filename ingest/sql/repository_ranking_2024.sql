-- Ranking of repositories by event count
SELECT
  repo.id                                         AS repo_id,
  ARRAY_AGG(repo.name ORDER BY created_at DESC LIMIT 1)[OFFSET(0)] AS latest_name,
  COUNT(DISTINCT repo.name)                       AS name_count,
  COUNT(*)                                        AS events,
  COUNTIF(type = 'IssuesEvent')                   AS issues_events,
  COUNTIF(type = 'PullRequestEvent')              AS pr_events,
  COUNTIF(type = 'IssueCommentEvent')             AS issue_comment_events,
  COUNTIF(type = 'PullRequestReviewEvent')        AS pr_review_events,
  COUNTIF(type = 'PullRequestReviewCommentEvent') AS pr_review_comment_events,
  MIN(created_at)                                 AS first_event,
  MAX(created_at)                                 AS last_event
FROM `githubarchive.month.2024*`
WHERE type IN ('IssuesEvent', 'PullRequestEvent', 'IssueCommentEvent',
               'PullRequestReviewEvent', 'PullRequestReviewCommentEvent')
GROUP BY repo_id
ORDER BY events DESC;
