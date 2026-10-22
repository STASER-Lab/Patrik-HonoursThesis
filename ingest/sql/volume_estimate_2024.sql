-- Raw volume estimate of the five event types from 12 Wednesdays (one per month in MMDD format).
WITH sample AS (
  SELECT type, BYTE_LENGTH(payload) AS payload_bytes
  FROM `githubarchive.day.2024*`
  WHERE _TABLE_SUFFIX IN ('0110','0214','0313','0410','0515','0612',
                          '0710','0814','0911','1016','1113','1211')
    AND type IN ('IssuesEvent', 'PullRequestEvent', 'IssueCommentEvent',
                 'PullRequestReviewEvent', 'PullRequestReviewCommentEvent')
)
SELECT
  type,
  COUNT(*)                                        AS events_in_sample,
  ROUND(SUM(payload_bytes) / 1e9, 2)              AS sample_gb,
  ROUND(AVG(payload_bytes) / 1e3, 1)              AS avg_kb_per_event,
  ROUND(SUM(payload_bytes) / 12 * 366 / 1e12, 3)  AS est_2024_tb   -- 12 days scaled to 366
FROM sample
GROUP BY type
ORDER BY est_2024_tb DESC;
