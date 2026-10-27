-- Weather tables for the visit planner.
-- Used by Postgres (queried through Zetaris) and by SQLite (sample mode).

CREATE TABLE IF NOT EXISTS forecast_periods (
    city              TEXT        NOT NULL,
    period_number     INTEGER     NOT NULL,
    period_name       TEXT,
    start_time        TIMESTAMPTZ NOT NULL,
    end_time          TIMESTAMPTZ NOT NULL,
    is_daytime        BOOLEAN,
    temperature_f     INTEGER,
    precip_chance     INTEGER,
    wind_speed        TEXT,
    short_forecast    TEXT,
    detailed_forecast TEXT,
    fetched_at        TIMESTAMPTZ NOT NULL,
    source_url        TEXT,
    PRIMARY KEY (city, start_time)
);

CREATE TABLE IF NOT EXISTS weather_alerts (
    city        TEXT        NOT NULL,
    alert_id    TEXT        NOT NULL,
    event       TEXT,
    severity    TEXT,
    urgency     TEXT,
    headline    TEXT,
    effective   TIMESTAMPTZ,
    expires     TIMESTAMPTZ,
    instruction TEXT,
    fetched_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (city, alert_id)
);

-- One row per city, for joining weather with other datasets (state, county FIPS).
CREATE TABLE IF NOT EXISTS cities (
    city          TEXT    NOT NULL PRIMARY KEY,
    name          TEXT,
    state         TEXT,
    state_name    TEXT,
    latitude      REAL,
    longitude     REAL,
    county_fips   TEXT,
    county_name   TEXT,
    county_zone   TEXT,
    forecast_zone TEXT,
    nws_office    TEXT,
    fetched_at    TIMESTAMPTZ
);
