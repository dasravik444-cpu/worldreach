"""Write the city campaign files of every market into config/<code>/ (run again after editing the lists).

    python scripts/make_markets.py

A market is a country: its folder holds _base.toml (written by hand: the country's rules, chains to leave out),
one file per city (made here: a circle that does not overlap its neighbours, the city's time zone, a short Lead ID
prefix) and fleet.toml (the order the cities are searched in, made here).
"""
from __future__ import annotations

from pathlib import Path

E, C, M, P = "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"
L, D = "Europe/London", "Europe/Dublin"
# slug, name, aliases, (lat, lng), radius km, time zone, Lead ID prefix
MARKETS = {
    "us": [
        ("austin", "Austin", ["Austin TX", "ATX", "Round Rock"], (30.2672, -97.7431), 25, C, "AUS"),
        ("nashville", "Nashville", ["Music City"], (36.1627, -86.7816), 20, C, "BNA"),
        ("denver", "Denver", ["Aurora", "Lakewood"], (39.7392, -104.9903), 25, M, "DEN"),
        ("charlotte", "Charlotte", ["Charlotte NC"], (35.2271, -80.8431), 20, E, "CLT"),
        ("raleigh", "Raleigh", ["Durham", "Cary", "Research Triangle"], (35.7796, -78.6382), 25, E, "RDU"),
        ("tampa", "Tampa", ["St. Petersburg", "St Pete", "Clearwater"], (27.9506, -82.4572), 30, E, "TPA"),
        ("phoenix", "Phoenix", ["Scottsdale", "Tempe", "Mesa", "Glendale", "Chandler"], (33.4484, -112.0740), 35, "America/Phoenix", "PHX"),
        ("san-diego", "San Diego", ["SD", "La Jolla", "Chula Vista"], (32.7157, -117.1611), 25, P, "SAN"),
        ("dallas", "Dallas", ["Dallas TX", "DFW", "Plano", "Irving", "Garland"], (32.7767, -96.7970), 25, C, "DAL"),
        ("atlanta", "Atlanta", ["ATL", "Decatur", "Sandy Springs"], (33.7490, -84.3880), 30, E, "ATL"),
        ("orlando", "Orlando", ["Kissimmee", "Winter Park"], (28.5383, -81.3792), 25, E, "MCO"),
        ("miami", "Miami", ["Miami Beach", "Coral Gables", "Hialeah", "Fort Lauderdale"], (25.7617, -80.1918), 30, E, "MIA"),
        ("houston", "Houston", ["Houston TX", "HTX"], (29.7604, -95.3698), 35, C, "HOU"),
        ("san-antonio", "San Antonio", ["San Antonio TX", "SATX"], (29.4241, -98.4936), 25, C, "SAT"),
        ("fort-worth", "Fort Worth", ["Fort Worth TX", "Arlington"], (32.7555, -97.3308), 20, C, "FTW"),
        ("seattle", "Seattle", ["Bellevue", "Redmond"], (47.6062, -122.3321), 25, P, "SEA"),
        ("portland", "Portland", ["Portland OR", "PDX"], (45.5152, -122.6784), 20, P, "PDX"),
        ("minneapolis", "Minneapolis", ["Saint Paul", "St. Paul", "Twin Cities"], (44.9778, -93.2650), 20, C, "MSP"),
        ("salt-lake-city", "Salt Lake City", ["SLC"], (40.7608, -111.8910), 20, M, "SLC"),
        ("las-vegas", "Las Vegas", ["Vegas", "Henderson", "Paradise"], (36.1699, -115.1398), 20, P, "LAS"),
        ("boston", "Boston", ["Cambridge", "Somerville", "Quincy"], (42.3601, -71.0589), 20, E, "BOS"),
        ("washington-dc", "Washington", ["Washington DC", "DC", "Arlington VA", "Alexandria", "Bethesda"], (38.9072, -77.0369), 20, E, "DCA"),
        ("philadelphia", "Philadelphia", ["Philly"], (39.9526, -75.1652), 20, E, "PHL"),
        ("chicago", "Chicago", ["Chicagoland", "Evanston"], (41.8781, -87.6298), 25, C, "CHI"),
        ("san-francisco", "San Francisco", ["SF", "Oakland", "Berkeley", "Bay Area"], (37.7749, -122.4194), 20, P, "SFO"),
        ("san-jose", "San Jose", ["Silicon Valley", "Santa Clara", "Sunnyvale"], (37.3382, -121.8863), 20, P, "SJC"),
        ("los-angeles", "Los Angeles", ["LA", "Hollywood", "Santa Monica", "Pasadena", "Long Beach"], (34.0522, -118.2437), 35, P, "LAX"),
        ("new-york", "New York", ["New York City", "NYC", "Manhattan", "Brooklyn", "Queens", "Bronx"], (40.7128, -74.0060), 25, E, "NYC"),
    ],
    "gb": [
        ("manchester", "Manchester", ["Salford", "Stockport", "Greater Manchester"], (53.4808, -2.2426), 15, L, "MAN"),
        ("leeds", "Leeds", ["Bradford", "West Yorkshire"], (53.8008, -1.5491), 15, L, "LDS"),
        ("bristol", "Bristol", ["Bath"], (51.4545, -2.5879), 15, L, "BRS"),
        ("birmingham", "Birmingham", ["Solihull", "West Midlands"], (52.4862, -1.8904), 18, L, "BHM"),
        ("edinburgh", "Edinburgh", ["Leith"], (55.9533, -3.1883), 12, L, "EDI"),
        ("glasgow", "Glasgow", ["Paisley"], (55.8642, -4.2518), 15, L, "GLA"),
        ("liverpool", "Liverpool", ["Merseyside", "Birkenhead"], (53.4084, -2.9916), 12, L, "LPL"),
        ("nottingham", "Nottingham", ["Derby"], (52.9548, -1.1581), 12, L, "NTM"),
        ("sheffield", "Sheffield", ["Rotherham"], (53.3811, -1.4701), 12, L, "SHF"),
        ("newcastle", "Newcastle", ["Newcastle upon Tyne", "Gateshead", "Tyneside"], (54.9783, -1.6178), 12, L, "NCL"),
        ("brighton", "Brighton", ["Hove"], (50.8225, -0.1372), 10, L, "BTN"),
        ("cardiff", "Cardiff", ["Caerdydd"], (51.4816, -3.1791), 12, L, "CDF"),
        ("belfast", "Belfast", [], (54.5973, -5.9301), 12, L, "BFS"),
        ("london", "London", ["Greater London", "Westminster", "Camden", "Hackney", "Southwark"], (51.5074, -0.1278), 25, L, "LON"),
    ],
    "ie": [
        ("dublin", "Dublin", ["Dublin City", "Dun Laoghaire", "Swords", "Tallaght"], (53.3498, -6.2603), 15, D, "DUB"),
        ("cork", "Cork", ["Cork City"], (51.8985, -8.4756), 12, D, "ORK"),
        ("galway", "Galway", ["Salthill"], (53.2707, -9.0568), 10, D, "GWY"),
        ("limerick", "Limerick", [], (52.6638, -8.6267), 10, D, "LMK"),
    ],
}
NAMES = {"us": "the US", "gb": "the UK", "ie": "Ireland"}

TEMPLATE = """# {name} - one city of the {market} campaigns (config/{code}/fleet.toml). Shared settings: _base.toml.
# Made by scripts/make_markets.py - edit the list there and run it again.
include = ["../shared/categories.toml", "_base.toml"]

[campaign]
id = "{code}-{slug}"
timezone = "{tz}"
lead_id_prefix = "{prefix}"

[area]
name = "{name}"
aliases = [{aliases}]
center = [{lat}, {lng}]
radius_km = {radius}
"""


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "config"
    for code, cities in MARKETS.items():
        out = root / code
        out.mkdir(parents=True, exist_ok=True)
        for slug, name, aliases, (lat, lng), radius, tz, prefix in cities:
            (out / f"{slug}.toml").write_text(TEMPLATE.format(
                name=name, slug=slug, tz=tz, prefix=prefix, code=code, market=NAMES[code],
                aliases=", ".join(f'"{a}"' for a in aliases), lat=lat, lng=lng, radius=radius), encoding="utf-8")
        lines = [f"# The cities of {NAMES[code]}, in the order they are searched (one at a time, each until it is done).",
                 '# Put "#" in front of a line to leave a city out. New cities: scripts/make_markets.py.',
                 "cities = ["] + [f'  "{c[0]}",' for c in cities] + ["]", ""]
        (out / "fleet.toml").write_text("\n".join(lines), encoding="utf-8")
        print(f"{code}: {len(cities)} city files in {out}")


if __name__ == "__main__":
    main()
