-- Compare candidate filter rules for removing bot and test repositories.
WITH j AS (
  SELECT r.repo_id, r.events, a.distinct_actors,
         SAFE_DIVIDE(a.top_actor_events, r.events) AS top_share,
         SAFE_DIVIDE(a.bot_events, r.events)       AS bot_share
  FROM `insert saved ranking table name here` r
  JOIN `insert saved actors table name here` a USING (repo_id)
),
f AS (
  SELECT 'a: no filter'                 AS rule, * FROM j
  UNION ALL SELECT 'b: actors >= 2',            * FROM j WHERE distinct_actors >= 2
  UNION ALL SELECT 'c: actors >= 3',            * FROM j WHERE distinct_actors >= 3
  UNION ALL SELECT 'd: actors >= 5',            * FROM j WHERE distinct_actors >= 5
  UNION ALL SELECT 'e: actors >= 3, top <= 0.8', * FROM j WHERE distinct_actors >= 3 AND top_share <= 0.8
  UNION ALL SELECT 'f: actors >= 3, top <= 0.5', * FROM j WHERE distinct_actors >= 3 AND top_share <= 0.5
  UNION ALL SELECT 'g: e + events/actor <= 1000', * FROM j WHERE distinct_actors >= 3 AND top_share <= 0.8 AND events / distinct_actors <= 1000
  UNION ALL SELECT 'h: e + events/actor <= 500',  * FROM j WHERE distinct_actors >= 3 AND top_share <= 0.8 AND events / distinct_actors <= 500
)
SELECT
  rule,
  COUNT(*)                                   AS repos,
  SUM(events)                                AS events,
  ROUND(SUM(events) / 283880836, 3)          AS share_of_all_events,
  APPROX_QUANTILES(events, 100)[OFFSET(50)]  AS p50_events,
  APPROX_QUANTILES(events, 100)[OFFSET(99)]  AS p99_events,
  MAX(events)                                AS max_events
FROM f
GROUP BY rule
ORDER BY rule;
