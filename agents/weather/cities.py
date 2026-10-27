"""US cities the visit planner covers, plus a resolver that finds a city in free text.

Coverage: the 50 largest US cities, plus the 4 largest cities in every state (checked against
the Wikipedia list of largest cities by state) and DC, plus a few extra well-known ones.
Each city's id is "Name, ST" (e.g. "Portland, OR"), which is also the value of the
`city` column in the weather tables.
"""
import re

STATES = {
    "AL": ("Alabama", "01"), "AK": ("Alaska", "02"), "AZ": ("Arizona", "04"),
    "AR": ("Arkansas", "05"), "CA": ("California", "06"), "CO": ("Colorado", "08"),
    "CT": ("Connecticut", "09"), "DE": ("Delaware", "10"), "DC": ("District of Columbia", "11"),
    "FL": ("Florida", "12"), "GA": ("Georgia", "13"), "HI": ("Hawaii", "15"),
    "ID": ("Idaho", "16"), "IL": ("Illinois", "17"), "IN": ("Indiana", "18"),
    "IA": ("Iowa", "19"), "KS": ("Kansas", "20"), "KY": ("Kentucky", "21"),
    "LA": ("Louisiana", "22"), "ME": ("Maine", "23"), "MD": ("Maryland", "24"),
    "MA": ("Massachusetts", "25"), "MI": ("Michigan", "26"), "MN": ("Minnesota", "27"),
    "MS": ("Mississippi", "28"), "MO": ("Missouri", "29"), "MT": ("Montana", "30"),
    "NE": ("Nebraska", "31"), "NV": ("Nevada", "32"), "NH": ("New Hampshire", "33"),
    "NJ": ("New Jersey", "34"), "NM": ("New Mexico", "35"), "NY": ("New York", "36"),
    "NC": ("North Carolina", "37"), "ND": ("North Dakota", "38"), "OH": ("Ohio", "39"),
    "OK": ("Oklahoma", "40"), "OR": ("Oregon", "41"), "PA": ("Pennsylvania", "42"),
    "RI": ("Rhode Island", "44"), "SC": ("South Carolina", "45"), "SD": ("South Dakota", "46"),
    "TN": ("Tennessee", "47"), "TX": ("Texas", "48"), "UT": ("Utah", "49"),
    "VT": ("Vermont", "50"), "VA": ("Virginia", "51"), "WA": ("Washington", "53"),
    "WV": ("West Virginia", "54"), "WI": ("Wisconsin", "55"), "WY": ("Wyoming", "56"),
}

# (name, state, latitude, longitude). The first 50 are the largest US cities.
_RAW = [
    ("New York", "NY", 40.7128, -74.0060), ("Los Angeles", "CA", 34.0522, -118.2437),
    ("Chicago", "IL", 41.8781, -87.6298), ("Houston", "TX", 29.7604, -95.3698),
    ("Phoenix", "AZ", 33.4484, -112.0740), ("Philadelphia", "PA", 39.9526, -75.1652),
    ("San Antonio", "TX", 29.4241, -98.4936), ("San Diego", "CA", 32.7157, -117.1611),
    ("Dallas", "TX", 32.7767, -96.7970), ("Jacksonville", "FL", 30.3322, -81.6557),
    ("Fort Worth", "TX", 32.7555, -97.3308), ("Austin", "TX", 30.2672, -97.7431),
    ("San Jose", "CA", 37.3382, -121.8863), ("Charlotte", "NC", 35.2271, -80.8431),
    ("Columbus", "OH", 39.9612, -82.9988), ("Indianapolis", "IN", 39.7684, -86.1581),
    ("San Francisco", "CA", 37.7749, -122.4194), ("Seattle", "WA", 47.6062, -122.3321),
    ("Denver", "CO", 39.7392, -104.9903), ("Oklahoma City", "OK", 35.4676, -97.5164),
    ("Nashville", "TN", 36.1627, -86.7816), ("Washington", "DC", 38.9072, -77.0369),
    ("El Paso", "TX", 31.7619, -106.4850), ("Las Vegas", "NV", 36.1699, -115.1398),
    ("Boston", "MA", 42.3601, -71.0589), ("Detroit", "MI", 42.3314, -83.0458),
    ("Portland", "OR", 45.5152, -122.6784), ("Louisville", "KY", 38.2527, -85.7585),
    ("Memphis", "TN", 35.1495, -90.0490), ("Baltimore", "MD", 39.2904, -76.6122),
    ("Milwaukee", "WI", 43.0389, -87.9065), ("Albuquerque", "NM", 35.0844, -106.6504),
    ("Tucson", "AZ", 32.2226, -110.9747), ("Fresno", "CA", 36.7378, -119.7871),
    ("Sacramento", "CA", 38.5816, -121.4944), ("Mesa", "AZ", 33.4152, -111.8315),
    ("Atlanta", "GA", 33.7490, -84.3880), ("Kansas City", "MO", 39.0997, -94.5786),
    ("Colorado Springs", "CO", 38.8339, -104.8214), ("Omaha", "NE", 41.2565, -95.9345),
    ("Raleigh", "NC", 35.7796, -78.6382), ("Miami", "FL", 25.7617, -80.1918),
    ("Virginia Beach", "VA", 36.8000, -76.0500), ("Long Beach", "CA", 33.7701, -118.1937),
    ("Oakland", "CA", 37.8044, -122.2712), ("Minneapolis", "MN", 44.9778, -93.2650),
    ("Bakersfield", "CA", 35.3733, -119.0187), ("Tulsa", "OK", 36.1540, -95.9928),
    ("Tampa", "FL", 27.9506, -82.4572), ("Arlington", "TX", 32.7357, -97.1081),
    # Largest 3-4 cities in each state (skipping ones already above)
    ("Huntsville", "AL", 34.7304, -86.5861), ("Birmingham", "AL", 33.5186, -86.8104),
    ("Montgomery", "AL", 32.3792, -86.3077), ("Mobile", "AL", 30.6954, -88.0399),
    ("Anchorage", "AK", 61.2181, -149.9003), ("Fairbanks", "AK", 64.8378, -147.7164),
    ("Juneau", "AK", 58.3019, -134.4197),
    ("Chandler", "AZ", 33.3062, -111.8413),
    ("Little Rock", "AR", 34.7465, -92.2896), ("Fayetteville", "AR", 36.0626, -94.1574),
    ("Fort Smith", "AR", 35.3859, -94.3985), ("Springdale", "AR", 36.1867, -94.1288),
    ("Aurora", "CO", 39.7294, -104.8319), ("Fort Collins", "CO", 40.5853, -105.0844),
    ("Bridgeport", "CT", 41.1865, -73.1952), ("Stamford", "CT", 41.0534, -73.5387),
    ("New Haven", "CT", 41.3083, -72.9279), ("Hartford", "CT", 41.7658, -72.6734),
    ("Wilmington", "DE", 39.7391, -75.5398), ("Dover", "DE", 39.1582, -75.5244),
    ("Newark", "DE", 39.6837, -75.7497),
    ("Orlando", "FL", 28.5383, -81.3792),
    ("Columbus", "GA", 32.4610, -84.9877), ("Augusta", "GA", 33.4735, -82.0105),
    ("Savannah", "GA", 32.0809, -81.0912),
    ("Honolulu", "HI", 21.3069, -157.8583), ("Hilo", "HI", 19.7241, -155.0868),
    ("Kailua", "HI", 21.4022, -157.7394), ("Kahului", "HI", 20.8893, -156.4729),
    ("Boise", "ID", 43.6150, -116.2023), ("Meridian", "ID", 43.6121, -116.3915),
    ("Nampa", "ID", 43.5407, -116.5635), ("Idaho Falls", "ID", 43.4917, -112.0339),
    ("Aurora", "IL", 41.7606, -88.3201), ("Joliet", "IL", 41.5250, -88.0817),
    ("Naperville", "IL", 41.7508, -88.1535),
    ("Fort Wayne", "IN", 41.0793, -85.1394), ("Evansville", "IN", 37.9716, -87.5711),
    ("South Bend", "IN", 41.6764, -86.2520),
    ("Des Moines", "IA", 41.5868, -93.6250), ("Cedar Rapids", "IA", 41.9779, -91.6656),
    ("Davenport", "IA", 41.5236, -90.5776), ("Sioux City", "IA", 42.4963, -96.4049),
    ("Wichita", "KS", 37.6872, -97.3301), ("Overland Park", "KS", 38.9822, -94.6708),
    ("Kansas City", "KS", 39.1142, -94.6275), ("Olathe", "KS", 38.8814, -94.8191),
    ("Lexington", "KY", 38.0406, -84.5037), ("Bowling Green", "KY", 36.9685, -86.4808),
    ("Owensboro", "KY", 37.7719, -87.1112),
    ("New Orleans", "LA", 29.9511, -90.0715), ("Baton Rouge", "LA", 30.4515, -91.1871),
    ("Shreveport", "LA", 32.5252, -93.7502), ("Lafayette", "LA", 30.2241, -92.0198),
    ("Portland", "ME", 43.6591, -70.2568), ("Lewiston", "ME", 44.1004, -70.2148),
    ("Bangor", "ME", 44.8016, -68.7712),
    ("Frederick", "MD", 39.4143, -77.4105), ("Rockville", "MD", 39.0840, -77.1528),
    ("Gaithersburg", "MD", 39.1434, -77.2014),
    ("Worcester", "MA", 42.2626, -71.8023), ("Springfield", "MA", 42.1015, -72.5898),
    ("Cambridge", "MA", 42.3736, -71.1097),
    ("Grand Rapids", "MI", 42.9634, -85.6681), ("Warren", "MI", 42.5145, -83.0147),
    ("Sterling Heights", "MI", 42.5803, -83.0302),
    ("Saint Paul", "MN", 44.9537, -93.0900), ("Rochester", "MN", 44.0121, -92.4802),
    ("Duluth", "MN", 46.7867, -92.1005),
    ("Jackson", "MS", 32.2988, -90.1848), ("Gulfport", "MS", 30.3674, -89.0928),
    ("Southaven", "MS", 34.9889, -90.0126), ("Hattiesburg", "MS", 31.3271, -89.2903),
    ("St. Louis", "MO", 38.6270, -90.1994), ("Springfield", "MO", 37.2090, -93.2923),
    ("Columbia", "MO", 38.9517, -92.3341),
    ("Billings", "MT", 45.7833, -108.5007), ("Missoula", "MT", 46.8721, -113.9940),
    ("Great Falls", "MT", 47.5053, -111.3008), ("Bozeman", "MT", 45.6770, -111.0429),
    ("Lincoln", "NE", 40.8136, -96.7026), ("Bellevue", "NE", 41.1544, -95.9146),
    ("Grand Island", "NE", 40.9264, -98.3420),
    ("Henderson", "NV", 36.0395, -114.9817), ("Reno", "NV", 39.5296, -119.8138),
    ("North Las Vegas", "NV", 36.1989, -115.1175),
    ("Manchester", "NH", 42.9956, -71.4548), ("Nashua", "NH", 42.7654, -71.4676),
    ("Concord", "NH", 43.2081, -71.5376),
    ("Newark", "NJ", 40.7357, -74.1724), ("Jersey City", "NJ", 40.7178, -74.0431),
    ("Paterson", "NJ", 40.9168, -74.1718), ("Elizabeth", "NJ", 40.6640, -74.2107),
    ("Las Cruces", "NM", 32.3199, -106.7637), ("Rio Rancho", "NM", 35.2328, -106.6630),
    ("Santa Fe", "NM", 35.6870, -105.9378),
    ("Buffalo", "NY", 42.8864, -78.8784), ("Yonkers", "NY", 40.9312, -73.8988),
    ("Rochester", "NY", 43.1566, -77.6088),
    ("Greensboro", "NC", 36.0726, -79.7920), ("Durham", "NC", 35.9940, -78.8986),
    ("Fargo", "ND", 46.8772, -96.7898), ("Bismarck", "ND", 46.8083, -100.7837),
    ("Grand Forks", "ND", 47.9253, -97.0329), ("Minot", "ND", 48.2325, -101.2963),
    ("Cleveland", "OH", 41.4993, -81.6944), ("Cincinnati", "OH", 39.1031, -84.5120),
    ("Toledo", "OH", 41.6528, -83.5379),
    ("Norman", "OK", 35.2226, -97.4395), ("Broken Arrow", "OK", 36.0526, -95.7969),
    ("Eugene", "OR", 44.0521, -123.0868), ("Salem", "OR", 44.9429, -123.0351),
    ("Gresham", "OR", 45.4983, -122.4302),
    ("Pittsburgh", "PA", 40.4406, -79.9959), ("Allentown", "PA", 40.6084, -75.4902),
    ("Reading", "PA", 40.3356, -75.9269),
    ("Providence", "RI", 41.8240, -71.4128), ("Warwick", "RI", 41.7240, -71.4600),
    ("Cranston", "RI", 41.7798, -71.4373),
    ("Charleston", "SC", 32.7765, -79.9311), ("Columbia", "SC", 34.0007, -81.0348),
    ("North Charleston", "SC", 32.8546, -79.9748), ("Mount Pleasant", "SC", 32.7941, -79.8626),
    ("Sioux Falls", "SD", 43.5446, -96.7311), ("Rapid City", "SD", 44.0805, -103.2310),
    ("Aberdeen", "SD", 45.4647, -98.4865),
    ("Knoxville", "TN", 35.9606, -83.9207), ("Chattanooga", "TN", 35.0456, -85.3097),
    ("Salt Lake City", "UT", 40.7608, -111.8910), ("West Valley City", "UT", 40.6916, -112.0011),
    ("West Jordan", "UT", 40.6097, -111.9391), ("Provo", "UT", 40.2338, -111.6585),
    ("Burlington", "VT", 44.4759, -73.2121), ("South Burlington", "VT", 44.4669, -73.1710),
    ("Rutland", "VT", 43.6106, -72.9726),
    ("Chesapeake", "VA", 36.7682, -76.2875), ("Norfolk", "VA", 36.8508, -76.2859),
    ("Richmond", "VA", 37.5407, -77.4360),
    ("Spokane", "WA", 47.6588, -117.4260), ("Tacoma", "WA", 47.2529, -122.4443),
    ("Vancouver", "WA", 45.6387, -122.6615),
    ("Charleston", "WV", 38.3498, -81.6326), ("Huntington", "WV", 38.4192, -82.4452),
    ("Morgantown", "WV", 39.6295, -79.9559), ("Parkersburg", "WV", 39.2667, -81.5615),
    ("Madison", "WI", 43.0731, -89.4012), ("Green Bay", "WI", 44.5133, -88.0133),
    ("Kenosha", "WI", 42.5847, -87.8212),
    ("Cheyenne", "WY", 41.1400, -104.8202), ("Casper", "WY", 42.8501, -106.3252),
    ("Laramie", "WY", 41.3114, -105.5911), ("Gillette", "WY", 44.2911, -105.5022),
    # Added after checking each state's top 4 against the Wikipedia population list
    ("Wasilla", "AK", 61.5814, -149.4394), ("Gilbert", "AZ", 33.3528, -111.7890),
    ("Macon", "GA", 32.8407, -83.6324), ("East Honolulu", "HI", 21.2890, -157.7170),
    ("Pearl City", "HI", 21.3972, -157.9752), ("Caldwell", "ID", 43.6629, -116.6874),
    ("Carmel", "IN", 39.9784, -86.1180), ("Bloomington", "MN", 44.8408, -93.2983),
    ("Lakewood", "NJ", 40.0979, -74.2176), ("Dover", "NH", 43.1979, -70.8737),
    ("Pawtucket", "RI", 41.8787, -71.3826), ("Colchester", "VT", 44.5439, -73.1479),
    ("Brookings", "SD", 44.3114, -96.7984), ("South Portland", "ME", 43.6415, -70.2409),
    ("Middletown", "DE", 39.4496, -75.7163),
]

CITIES = {}
for _rank, (_name, _st, _lat, _lon) in enumerate(_RAW, start=1):
    _id = f"{_name}, {_st}"
    CITIES[_id] = {"id": _id, "name": _name, "state": _st, "state_name": STATES[_st][0],
                   "state_fips": STATES[_st][1], "lat": _lat, "lon": _lon, "rank": _rank}

# Nicknames people actually type -> city id
ALIASES = {
    "nyc": "New York, NY", "new york city": "New York, NY", "manhattan": "New York, NY",
    "brooklyn": "New York, NY", "queens": "New York, NY", "the bronx": "New York, NY",
    "la": "Los Angeles, CA", "l.a.": "Los Angeles, CA", "sf": "San Francisco, CA",
    "san fran": "San Francisco, CA", "dc": "Washington, DC", "d.c.": "Washington, DC",
    "washington dc": "Washington, DC", "philly": "Philadelphia, PA", "vegas": "Las Vegas, NV",
    "nola": "New Orleans, LA", "slc": "Salt Lake City, UT", "okc": "Oklahoma City, OK",
    "st louis": "St. Louis, MO", "saint louis": "St. Louis, MO", "st. paul": "Saint Paul, MN",
    "st paul": "Saint Paul, MN",
}
# Backwards-compatible short ids used earlier in the project
LEGACY_IDS = {"LA": "Los Angeles, CA", "NYC": "New York, NY"}

_CODES_BY_NAME = {v[0].lower(): k for k, v in STATES.items()}


def _pattern(phrase):
    return re.compile(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", re.I)


# phrase -> list of city ids (a name like "Portland" maps to several)
_PHRASES = {}
for cid, c in CITIES.items():
    _PHRASES.setdefault(c["name"].lower(), []).append(cid)
for alias, cid in ALIASES.items():
    _PHRASES.setdefault(alias, []).append(cid)
# When several cities share a name, the bigger one is the default.
PREFERRED = {"Springfield, MO", "Columbia, SC", "Rochester, NY"}
for k in _PHRASES:
    _PHRASES[k] = sorted(set(_PHRASES[k]),
                         key=lambda i: (i not in PREFERRED, CITIES[i]["rank"]))
_ORDERED = sorted(_PHRASES, key=len, reverse=True)
_COMPILED = [(p, _pattern(p)) for p in _ORDERED]
_STATE_NAME_PATS = sorted(_CODES_BY_NAME, key=len, reverse=True)


def get_city(city):
    """Exact lookup by id ('Portland, ME'), legacy id ('NYC') or case-insensitive id."""
    key = str(city).strip()
    if key in CITIES:
        return CITIES[key]
    if key.upper() in LEGACY_IDS:
        return CITIES[LEGACY_IDS[key.upper()]]
    for cid in CITIES:
        if cid.lower() == key.lower():
            return CITIES[cid]
    return None


def resolve_city(text):
    """Find the city a question is about.

    Returns (city_id or None, note or None). The note explains any assumption,
    e.g. which Portland was picked when no state was given.
    """
    raw = text or ""
    masked = raw.lower()
    matches = []  # (start, phrase, ids, matched_text)
    for phrase, pat in _COMPILED:
        for m in pat.finditer(masked):
            matches.append((m.start(), phrase, _PHRASES[phrase], raw[m.start():m.end()]))
            masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]

    # States mentioned outside city names: full names anywhere, 2-letter codes only in capitals.
    hints = set()
    for name in _STATE_NAME_PATS:
        if _pattern(name).search(masked):
            hints.add(_CODES_BY_NAME[name])
    for code in re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", raw):
        if code in STATES and not any(m[3] == code for m in matches):
            hints.add(code)

    # A matched "city" that is really a state ("Buffalo, New York", "New Orleans, LA")
    # becomes a state hint when another city was also matched.
    if len(matches) > 1:
        kept = []
        for m in matches:
            as_state = _CODES_BY_NAME.get(m[1]) or (m[3] if m[3] in STATES else None)
            others = [o for o in matches if o is not m]
            if as_state and any(CITIES[i]["state"] == as_state for o in others for i in o[2]):
                hints.add(as_state)
            else:
                kept.append(m)
        matches = kept

    if not matches:
        return None, None
    matches.sort(key=lambda m: m[0])
    ids = matches[0][2]
    if hints:
        in_state = [i for i in ids if CITIES[i]["state"] in hints]
        ids = in_state or ids
    chosen = ids[0]
    note = None
    if len(ids) > 1:
        others = ", ".join(i for i in ids[1:])
        note = f"Assumed {chosen}. If you meant {others}, include the state."
    return chosen, note
