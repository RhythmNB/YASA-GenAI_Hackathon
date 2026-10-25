-- =============================================================================
-- Source:   CDC National Wastewater Surveillance System (NWSS) -- SARS-CoV-2
--           wastewater concentration data
-- Note:     numeric fields in this export carry embedded thousands separators
--           inside quotes (e.g. "3,000", "15,486.27946"), so inferSchema reads
--           them as strings. Cast with REPLACE(col, ',', '') when aggregating;
--           see 01_wastewater_select.sql.
-- =============================================================================
CREATE LIGHTNING DATABASE wastewater DESCRIBE BY "CDC NWSS SARS-CoV-2 wastewater surveillance, data.cdc.gov export 2026-10-23";

CREATE LIGHTNING FILESTORE TABLE sars_cov_2 FROM wastewater FORMAT CSV OPTIONS (
  PATH "file:///home/zetaris/customer-data/shared/wastewater/CDC_Wastewater_Data_for_SARS-CoV-2_20261023.csv",
  header "true",
  inferSchema "true",
  delimiter ",",
  quote "\"",
  escape "\""
);

-- Next: verify with sql/01_wastewater_select.sql
