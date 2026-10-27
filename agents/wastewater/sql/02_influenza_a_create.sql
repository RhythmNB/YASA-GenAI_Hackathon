-- =============================================================================
-- Source:   CDC National Wastewater Surveillance System (NWSS) -- Influenza A
--           wastewater data, data.cdc.gov dataset ymmh-divb
--           https://data.cdc.gov/api/views/ymmh-divb/rows.csv?accessType=DOWNLOAD
--           Export downloaded 2026-10-26 (CDC updates it on Fridays).
--           Loaded: 338,192 rows, 1,507 sites, 52 states/territories, samples
--           2021-09-15 to 2026-10-20, pcr_target = 'fluav', units copies/l wastewater
--           (72%) and copies/g dry sludge (28%).
-- Format:   CSV, quoted, header row, same NWSS layout as the SARS-CoV-2 export
--           (site, state_territory, counties_served, sample_collect_date,
--           pcr_target, pcr_target_detect, pcr_target_avg_conc, pcr_target_units, ...)
-- Location: copied from F:\Hackathon\YASA-GenAI_Hackathon\wastewater\data\
--           CDC_Wastewater_Data_for_Influenza_A_20261026.csv into the Zetaris driver
--           container (docker cp zetaris-driver-1:...) at
--           /home/zetaris/customer-data/shared/wastewater/CDC_Wastewater_Data_for_Influenza_A_20261026.csv
-- Note:     numeric fields carry embedded thousands separators inside quotes, so
--           inferSchema reads them as strings; the agent casts with REPLACE(col, ',', '').
-- Refresh:  download the CSV again, docker cp it over the same path, then
--           DROP TABLE wastewater.influenza_a and re-run this script.
-- Run:      python -m wastewater_agent is not needed; use the JDBC runner:
--           python scripts/run_sql.py --channel jdbc ../wastewater/sql/02_influenza_a_create.sql
--           (from F:\Hackathon\getting-started, JAVA_HOME set), or the one-off
--           Python snippet in the project notes.
-- =============================================================================
-- The database `wastewater` already exists (01_wastewater_create.sql).

CREATE LIGHTNING FILESTORE TABLE influenza_a FROM wastewater FORMAT CSV OPTIONS (
  PATH "file:///home/zetaris/customer-data/shared/wastewater/CDC_Wastewater_Data_for_Influenza_A_20261026.csv",
  header "true",
  inferSchema "true",
  delimiter ",",
  quote "\"",
  escape "\""
);

-- Next: verify with sql/02_influenza_a_select.sql
