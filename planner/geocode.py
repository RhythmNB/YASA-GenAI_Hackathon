"""Destination lookup through Zetaris.

The Open-Meteo geocoding API is registered in Zetaris as REST tables in the
GEOCODING database, one per city name (a Zetaris REST table binds one fixed URL,
so the city name is part of the table's endpoint). The first plan for a city
registers its table; later plans query it live, so every lookup is an API call
made by Zetaris, not by this server.

    GEOCODING.city_richmond  ->  https://geocoding-api.open-meteo.com/v1/search?name=Richmond&count=20&...

resolve() returns the result matching the trip's state, picking the most
populous match when a state has several places of that name."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from wastewater_agent.states import normalize_county, state_name
from wastewater_agent.zetaris import JdbcClient, ZetarisError

DATABASE = "GEOCODING"
API = "https://geocoding-api.open-meteo.com/v1/search?name={name}&count=20&language=en&format=json&countryCode=US"


@dataclass
class Place:
    name: str
    state: str
    county: str | None
    lat: float
    lon: float
    population: int | None
    table: str
    seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state, "county": self.county, "lat": self.lat, "lon": self.lon,
                "population": self.population, "table": self.table, "seconds": round(self.seconds, 1)}


def table_for(city: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", city.lower()).strip("_") or "place"
    return f"city_{slug}"


def _execute(client: JdbcClient, sql: str) -> list[dict[str, Any]]:
    """A plain JDBC Statement: the '?' in an endpoint URL must not be read as a bind parameter,
    which the driver's PreparedStatement (used by JdbcClient.query) would do."""
    client.connect()
    st = client._conn.jconn.createStatement()  # noqa: SLF001  the client exposes no raw-statement call
    try:
        if not st.execute(sql):
            return []
        rs = st.getResultSet(); md = rs.getMetaData(); n = md.getColumnCount()
        cols = [str(md.getColumnLabel(c)) for c in range(1, n + 1)]
        out = []
        while rs.next():
            out.append({cols[c - 1]: (None if rs.getObject(c) is None else str(rs.getObject(c))) for c in range(1, n + 1)})
        return out
    finally:
        st.close()


def _ensure(client: JdbcClient, city: str) -> str:
    table = table_for(city)
    name = re.sub(r"[^A-Za-z0-9 .'-]", "", city).strip().replace(" ", "%20")
    for sql in (f'CREATE LIGHTNING DATABASE {DATABASE} DESCRIBE BY "Open-Meteo geocoding API, one REST table per city name"',
                f'''CREATE LIGHTNING REST TABLE {table} FROM {DATABASE} REQUEST (
                      endpoint "{API.format(name=name)}",
                      method "get", response_type "json", http_encoding "URLENCODED"
                    ) HEADER () BODY ()'''):
        try:
            _execute(client, sql)
        except Exception as e:  # noqa: BLE001  "already exists" is the normal case after the first plan
            if "exist" not in str(e).lower():
                raise ZetarisError(f"could not register {DATABASE}.{table}: {str(e)[:200]}") from e
    return f"{DATABASE.lower()}.{table}"


def resolve(client: JdbcClient, city: str, state_code: str) -> Place | None:
    """The place called `city` in the state `state_code`, looked up through Zetaris; None if the
    API has no such place."""
    t0 = time.perf_counter()
    table = _ensure(client, city)
    try:
        rows = _execute(client, f"""SELECT r.name AS name, r.admin1 AS state, r.admin2 AS county, r.latitude AS lat,
                                           r.longitude AS lon, r.population AS population
                                    FROM (SELECT explode(results) AS r FROM {table}) t""")
    except Exception as e:  # noqa: BLE001
        if "results" not in str(e):
            raise
        # The API answered without a "results" field: no such place. Drop the empty table.
        try:
            _execute(client, f"DROP LIGHTNING DATABASE TABLE {table}")
        except Exception:  # noqa: BLE001
            pass
        return None
    want = state_name(state_code).lower()
    matches = [r for r in rows if (r.get("state") or "").lower() == want]
    if not matches:
        return None
    best = max(matches, key=lambda r: float(r.get("population") or 0))
    return Place(name=best["name"], state=best["state"], county=normalize_county(best.get("county")),
                 lat=float(best["lat"]), lon=float(best["lon"]),
                 population=int(float(best["population"])) if best.get("population") else None,
                 table=table, seconds=time.perf_counter() - t0)
