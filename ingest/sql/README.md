# BigQuery Experiment Steps

These are the preliminary steps I followed to gain a high-level overview of the GH Archive 2024 dataset.

**NOTE:** The Google BigQuery sandbox allows 1 TB of FREE queries per month (As of October 20th, 2026).
See the BigQuery [docs](https://docs.cloud.google.com/bigquery/docs/sandbox) for more information.
The queries can be run in the BigQuery console. Here you can also view the query's estimated size.
Modify these queries to your needs. For example, you may want 2023 data instead.


1. Run `repository_ranking_2024.sql`

    * Make sure to save the results a table in your BigQuery project for the next steps.

2. Run `ranking_shape.sql`

    * Requires the `repo_ranking_2024` table, which is created by ingest/sql/repository_ranking_2024.sql.
    * Make sure to replace the placeholder paths with the actual table name below.

3. Run `volume_estimate_2024.sql`
    * BYTE_LENGTH(payload) measures the payload only, not the full event JSON so treat the result as a lower bound.
