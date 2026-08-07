"""Hand-aware static Statcast park factors (100 is neutral)."""
from __future__ import annotations

# A compact, intentionally auditable table. Unknown venues stay neutral.
PARKS = {
    "Coors Field": (121, 119, 122), "Great American Ball Park": (115, 118, 113),
    "Yankee Stadium": (113, 125, 105), "Citizens Bank Park": (110, 113, 108),
    "Fenway Park": (107, 115, 96), "Wrigley Field": (105, 105, 105),
    "Globe Life Field": (108, 109, 107), "Chase Field": (104, 105, 103),
    "Rogers Centre": (103, 103, 103), "Daikin Park": (102, 99, 104),
    "Minute Maid Park": (102, 99, 104), "Truist Park": (101, 101, 101),
    "Dodger Stadium": (97, 97, 97), "Petco Park": (94, 95, 93),
    "T-Mobile Park": (93, 93, 93), "Oracle Park": (88, 82, 92),
    "Citi Field": (99, 98, 99), "Target Field": (100, 99, 101),
    "PNC Park": (98, 92, 102), "Camden Yards": (99, 102, 97),
    "Oriole Park at Camden Yards": (99, 102, 97), "Rate Field": (105, 103, 107),
    "Guaranteed Rate Field": (105, 103, 107), "American Family Field": (99, 100, 98),
    "loanDepot park": (95, 95, 95), "Tropicana Field": (96, 96, 96),
}

PARK_DETAILS = {
    "Coors Field": (39.756, -104.994, "open", 0), "Great American Ball Park": (39.097, -84.507, "open", 30), "Yankee Stadium": (40.829, -73.926, "open", 22), "Citizens Bank Park": (39.906, -75.166, "open", 18), "Fenway Park": (42.346, -71.097, "open", 50), "Wrigley Field": (41.948, -87.655, "open", 38), "Globe Life Field": (32.747, -97.083, "retractable", 11), "Chase Field": (33.445, -112.067, "retractable", 23), "Rogers Centre": (43.641, -79.389, "retractable", 0), "Daikin Park": (29.757, -95.355, "retractable", 0), "Minute Maid Park": (29.757, -95.355, "retractable", 0), "Dodger Stadium": (34.073, -118.240, "open", 22), "Petco Park": (32.707, -117.157, "open", 14), "T-Mobile Park": (47.591, -122.332, "retractable", 30), "Oracle Park": (37.779, -122.389, "open", 99), "Citi Field": (40.757, -73.846, "open", 24), "Target Field": (44.982, -93.278, "open", 26), "Camden Yards": (39.284, -76.622, "open", 18), "Oriole Park at Camden Yards": (39.284, -76.622, "open", 18), "Rate Field": (41.830, -87.634, "open", 35), "Guaranteed Rate Field": (41.830, -87.634, "open", 35), "loanDepot park": (25.778, -80.220, "retractable", 36), "Tropicana Field": (27.768, -82.653, "dome", 45),
}


def get_park(venue_name: str | None) -> dict:
    """Return the matching park and a clear unknown flag rather than guessing."""
    name = str(venue_name or "")
    match = next((key for key in PARKS if key.lower() == name.lower()), None)
    if match is None:
        return {"name": name or "Unknown", "hr_factor": 100, "hr_factor_l": 100, "hr_factor_r": 100, "unknown": True, "lat": None, "lon": None, "roof": "open", "cf_bearing": None}
    total, left, right = PARKS[match]
    lat, lon, roof, bearing = PARK_DETAILS.get(match, (None, None, "open", None))
    return {"name": match, "hr_factor": total, "hr_factor_l": left, "hr_factor_r": right, "unknown": False, "lat": lat, "lon": lon, "roof": roof, "cf_bearing": bearing}


def get_park_hand_factor(venue_name: str | None, bats: str | None) -> float:
    park = get_park(venue_name)
    hand = str(bats or "").upper()
    factor = park["hr_factor_l"] if hand == "L" else park["hr_factor_r"] if hand == "R" else park["hr_factor"]
    return factor / 100
