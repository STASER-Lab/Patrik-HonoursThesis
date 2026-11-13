-- People and bot activity per repository, for filtering out bot and test repositories.
-- bot_events is a lower bound: it only catches logins ending in [bot].
SELECT
  repo.id                                            AS repo_id,
  COUNT(DISTINCT actor.id)                           AS distinct_actors,
  COUNTIF(ENDS_WITH(actor.login, '[bot]'))           AS bot_events,
  APPROX_TOP_COUNT(actor.id, 1)[OFFSET(0)].count     AS top_actor_events
FROM `githubarchive.month.2024*`
WHERE type IN ('IssuesEvent', 'PullRequestEvent', 'IssueCommentEvent',
               'PullRequestReviewEvent', 'PullRequestReviewCommentEvent')
GROUP BY repo_id;
