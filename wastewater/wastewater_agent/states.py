"""US state and territory names to the lowercase codes used in `state_territory`."""

from __future__ import annotations

import re

US_STATES: dict[str, str] = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc",
    "washington dc": "dc", "puerto rico": "pr", "guam": "gu", "american samoa": "as",
    "northern mariana islands": "mp", "us virgin islands": "vi", "virgin islands": "vi",
}

CODES = frozenset(US_STATES.values())
_CODE_RE = re.compile(r"\b([A-Z]{2})\b")


def find_state(text: str) -> str | None:
    """A state code named in free text: full names first (longest match wins),
    then an upper-case two-letter code (so 'in', 'or', 'me' in prose are ignored)."""
    low = text.lower()
    best: tuple[int, str] | None = None
    for name, code in US_STATES.items():
        if re.search(rf"\b{re.escape(name)}\b", low):
            if best is None or len(name) > best[0]:
                best = (len(name), code)
    if best:
        return best[1]
    for m in _CODE_RE.finditer(text):
        code = m.group(1).lower()
        if code in CODES and code != "us":
            return code
    return None


_COUNTY_SUFFIX = re.compile(r"\s+(county|parish|borough|census area|municipio|municipality)$", re.I)
_CITY_OF = re.compile(r"^city of\s+(.+)$", re.I)
_COUNTY_OK = re.compile(r"^[a-z][a-z .'\-]{0,60}$", re.I)


def normalize_county(label: str | None) -> str | None:
    """Map a geocoder or user label onto the dataset's `counties_served` naming:
    'Henrico County' -> 'Henrico', 'City of Richmond' -> 'Richmond City',
    'San Francisco County' -> 'San Francisco'. Returns None when unusable."""
    if not label:
        return None
    s = " ".join(str(label).split()).strip()
    m = _CITY_OF.match(s)
    if m:
        s = f"{m.group(1)} City"
    else:
        s = _COUNTY_SUFFIX.sub("", s)
        if re.search(r"\s+city$", s, re.I):
            s = re.sub(r"\s+city$", " City", s, flags=re.I)
    s = s.strip(" ,")
    return s if _COUNTY_OK.match(s) else None


def county_label(county: str | None, code: str | None = None) -> str:
    """Display form: 'Henrico' -> 'Henrico County'; 'Richmond City' stays;
    Louisiana uses parishes and Alaska boroughs."""
    if not county:
        return ""
    if county.lower().endswith(" city"):
        return county
    unit = {"la": "Parish", "ak": "Borough"}.get((code or "").lower(), "County")
    return f"{county} {unit}"


def region_name(code: str | None, county: str | None = None) -> str:
    if code and county:
        return f"{county_label(county, code)}, {state_name(code)}"
    return state_name(code)


def state_name(code: str | None) -> str:
    if code is None:
        return "the United States (all reporting states)"
    for name, c in US_STATES.items():
        if c == code:
            return name.title()
    return code.upper()
