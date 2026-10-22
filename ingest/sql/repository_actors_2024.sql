-- Per-repository people and bot activity, to filter out bot and test repositories.
SELECT
  repo.id                                            AS repo_id,
  COUNT(DISTINCT actor.id)                           AS distinct_actors,
  COUNTIF(ENDS_WITH(actor.login, '[bot]'))           AS bot_events,
  APPROX_TOP_COUNT(actor.id, 1)[OFFSET(0)].count     AS top_actor_events
FROM `githubarchive.month.2024*`     
WHERE type IN ('IssuesEvent', 'PullRequestEvent', 'IssueCommentEvent',
               'PullRequestReviewEvent', 'PullRequestReviewCommentEvent')
GROUP BY repo_id;

-- How the top 10 look with the above columns
SELECT r.latest_name, r.events, a.distinct_actors,
        ROUND(a.bot_events / r.events, 2)       AS bot_share,
        ROUND(a.top_actor_events / r.events, 2) AS top_actor_share
FROM `insert saved ranking table name here` r JOIN `insert saved actors table name here` a USING (repo_id)
ORDER BY r.events DESC LIMIT 10;
