-- Verification and example queries for 02_influenza_a_create.sql.

-- === Verification ===
SELECT * FROM wastewater.influenza_a LIMIT 5;

DESCRIBE wastewater.influenza_a;

SELECT COUNT(*) AS total_rows, COUNT(DISTINCT site) AS distinct_sites, COUNT(DISTINCT state_territory) AS distinct_states FROM wastewater.influenza_a;

-- The agent's registry entry needs the exact target value, the units and the date range.
SELECT pcr_target, COUNT(*) AS samples FROM wastewater.influenza_a GROUP BY pcr_target;

SELECT pcr_target_units, COUNT(*) AS samples FROM wastewater.influenza_a GROUP BY pcr_target_units ORDER BY samples DESC;

SELECT MIN(sample_collect_date) AS first_sample, MAX(sample_collect_date) AS last_sample FROM wastewater.influenza_a;

SELECT pcr_target_detect, COUNT(*) AS samples FROM wastewater.influenza_a GROUP BY pcr_target_detect;

-- === Example queries ===
-- Sites per state over the most recent four weeks of data
SELECT state_territory, COUNT(DISTINCT site) AS sites, COUNT(*) AS samples FROM wastewater.influenza_a WHERE sample_collect_date >= DATE_SUB((SELECT MAX(sample_collect_date) FROM wastewater.influenza_a), 28) GROUP BY state_territory ORDER BY sites DESC LIMIT 15;

-- Counties served by sites in one state (same list format as the SARS-CoV-2 table)
SELECT counties_served, COUNT(DISTINCT site) AS sites FROM wastewater.influenza_a WHERE state_territory = 'va' GROUP BY counties_served ORDER BY sites DESC LIMIT 10;
