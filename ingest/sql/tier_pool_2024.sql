SELECT r.repo_id, r.events
FROM `insert saved ranking table name here` r
JOIN `insert saved actors table name here` a USING (repo_id)
WHERE a.distinct_actors >= 3
  AND SAFE_DIVIDE(a.top_actor_events, r.events) <= 0.8
  AND r.events / a.distinct_actors <= 1000
ORDER BY r.repo_id;
