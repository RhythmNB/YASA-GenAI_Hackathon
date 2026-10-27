-- Verification and example queries for 01_wastewater_create.sql.

-- === Verification ===
SELECT * FROM wastewater.sars_cov_2 LIMIT 5;

DESCRIBE wastewater.sars_cov_2;

-- Expect 626338 rows (file has 626339 lines including the header).
SELECT COUNT(*) AS total_rows, COUNT(DISTINCT site) AS distinct_sites, COUNT(DISTINCT state_territory) AS distinct_states FROM wastewater.sars_cov_2;

-- === Example queries ===
-- Samples per data source
SELECT source, COUNT(*) AS samples FROM wastewater.sars_cov_2 GROUP BY source ORDER BY samples DESC;

-- Date range covered
SELECT MIN(sample_collect_date) AS first_sample, MAX(sample_collect_date) AS last_sample FROM wastewater.sars_cov_2;

-- Top 10 states by population served (thousands separators stripped before casting)
SELECT state_territory, SUM(CAST(REPLACE(population_served, ',', '') AS BIGINT)) AS population_served FROM (SELECT DISTINCT site, state_territory, population_served FROM wastewater.sars_cov_2) s GROUP BY state_territory ORDER BY population_served DESC LIMIT 10;
