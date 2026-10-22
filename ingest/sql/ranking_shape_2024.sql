-- How activity is spread across repositories
SELECT
  COUNT(*)                                      AS repos,
  SUM(events)                                   AS total_events,
  APPROX_QUANTILES(events, 100)[OFFSET(50)]     AS p50_events,
  APPROX_QUANTILES(events, 100)[OFFSET(90)]     AS p90_events,
  APPROX_QUANTILES(events, 100)[OFFSET(99)]     AS p99_events,
  APPROX_QUANTILES(events, 1000)[OFFSET(999)]   AS p999_events,
  MAX(events)                                   AS max_events,
  COUNTIF(events = 1)                           AS repos_with_1_event,
  COUNTIF(events >= 100)                        AS repos_with_100plus,
  COUNTIF(events >= 10000)                      AS repos_with_10k_plus,
  COUNTIF(name_count > 1)                       AS renamed_in_2024
FROM `insert saved ranking table name here`; 

-- Share of all events in the 99th and 99.9th percentile of repositories
WITH t AS (
  SELECT APPROX_QUANTILES(events, 100)[OFFSET(99)]   AS p99,
         APPROX_QUANTILES(events, 1000)[OFFSET(999)] AS p999
  FROM `insert saved ranking table name here`
)
SELECT
  ROUND(SUM(IF(events >= p99,  events, 0)) / SUM(events), 3) AS share_top_1pct,
  ROUND(SUM(IF(events >= p999, events, 0)) / SUM(events), 3) AS share_top_0_1pct
FROM `insert saved ranking table name here`, t;

-- The 10 largest repositories by event count
SELECT latest_name, events, pr_events, issue_comment_events, pr_review_events, name_count
FROM `insert saved ranking table name here`
ORDER BY events DESC
LIMIT 10;
