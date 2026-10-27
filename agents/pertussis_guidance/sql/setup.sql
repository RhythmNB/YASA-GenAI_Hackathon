-- Visit Planner: Zetaris setup. Run each statement on its own, in order, in the SQL Workspace.
-- Before 6 and 9: copy the CSV into the driver container (see HANDOFF.md, "Load the reference files").

-- 1. Database for web-API (REST) tables
CREATE LIGHTNING DATABASE CDC_REST DESCRIBE BY "CDC open data REST source";

-- 2. Live CDC pertussis counts for 2026 (fetched from data.cdc.gov when queried)
CREATE LIGHTNING REST TABLE nndss_pertussis_2026 FROM CDC_REST REQUEST (
  endpoint "https://data.cdc.gov/resource/x9gk-5huc.json?label=Pertussis&year=2026&$limit=5000",
  method "get",
  response_type "json",
  http_encoding "URLENCODED"
) HEADER () BODY ();

-- 3. Container for the project's views
CREATE SCHEMASTORE CONTAINER visitplanner;

-- 4. One row per state, latest week: NY + NYC combined, missing counts kept as missing
CREATE SCHEMASTORE VIEW pertussis_state_latest WITH CONTAINER visitplanner AS
WITH latest AS (
  SELECT MAX(CAST(week AS INT)) AS wk FROM cdc_rest.nndss_pertussis_2026
),
s AS (
  SELECT
    CASE WHEN location1 = 'New York City' THEN 'New York' ELSE location1 END AS state,
    CAST(week AS INT)  AS mmwr_week,
    CAST(m3 AS DOUBLE) AS ytd,
    CAST(m4 AS DOUBLE) AS prev_ytd
  FROM cdc_rest.nndss_pertussis_2026 n
  JOIN latest ON CAST(n.week AS INT) = latest.wk
  WHERE location1 IS NOT NULL
)
SELECT
  state,
  MAX(mmwr_week) AS mmwr_week,
  CASE WHEN COUNT(ytd) = COUNT(*)      THEN SUM(ytd)      END AS ytd_cases,
  CASE WHEN COUNT(prev_ytd) = COUNT(*) THEN SUM(prev_ytd) END AS prev_ytd_cases,
  (COUNT(ytd) = COUNT(*) AND COUNT(prev_ytd) = COUNT(*)) AS data_ok
FROM s
GROUP BY state;

-- 5. Database for reference files (no brackets allowed in the description)
CREATE LIGHTNING DATABASE REFDATA DESCRIBE BY "Reference tables, Census and CDC guidance";

-- 6. Census 2025 state populations (copy the CSV in first)
CREATE LIGHTNING FILESTORE TABLE census_state_pop_2025 FROM REFDATA FORMAT CSV OPTIONS (
  path "file:///home/zetaris/customer-data/shared/census/census_state_pop_2025.csv",
  header "true",
  inferSchema "true"
);

-- 7. Rates per 100,000 (what the pertussis agent reads)
CREATE SCHEMASTORE VIEW pertussis_state_rates WITH CONTAINER visitplanner AS
SELECT
  p.state,
  p.mmwr_week,
  p.ytd_cases,
  p.prev_ytd_cases,
  CAST(c.POPESTIMATE2025 AS BIGINT) AS population_2025,
  ROUND(p.ytd_cases      / CAST(c.POPESTIMATE2025 AS DOUBLE) * 100000, 2) AS ytd_rate_per_100k,
  ROUND(p.prev_ytd_cases / CAST(c.POPESTIMATE2025 AS DOUBLE) * 100000, 2) AS prev_ytd_rate_per_100k,
  ROUND(p.ytd_cases / NULLIF(p.prev_ytd_cases, 0), 2) AS ratio_vs_last_year,
  p.data_ok
FROM visitplanner.pertussis_state_latest p
JOIN refdata.census_state_pop_2025 c
  ON p.state = c.NAME;

-- 8. Check: 52 rows, Arizona at the top with 13.37 per 100k
SELECT * FROM visitplanner.pertussis_state_rates ORDER BY ytd_rate_per_100k DESC;

-- 9. CDC guidance snippets (what the guidance agent reads; copy the CSV in first)
CREATE LIGHTNING FILESTORE TABLE cdc_guidance FROM REFDATA FORMAT CSV OPTIONS (
  path "file:///home/zetaris/customer-data/shared/guidance/cdc_guidance_2026-10-26.csv",
  header "true",
  inferSchema "true"
);

-- 10. Check: 12 rows
SELECT guidance_id, pathogen, audience FROM refdata.cdc_guidance;
