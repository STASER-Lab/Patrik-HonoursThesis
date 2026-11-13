-- The tier pool: repositories that pass rule g of filter_rules_2024.sql.
-- Export the result as ingest/select/pool.csv.
SELECT r.repo_id, r.events
FROM `your_project.your_dataset.repository_ranking_2024` r
JOIN `your_project.your_dataset.repository_actors_2024` a USING (repo_id)
WHERE a.distinct_actors >= 3
  AND SAFE_DIVIDE(a.top_actor_events, r.events) <= 0.8
  AND r.events / a.distinct_actors <= 1000
ORDER BY r.repo_id;
