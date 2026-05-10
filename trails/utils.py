import math


def estimate_time(distance_km: float, elevation_gain_m: int) -> float:
    """Naismith's rule: 1 h per 5 km + 1 h per 600 m elevation gain."""
    return (distance_km / 5.0) + (elevation_gain_m / 600.0)


def haversine_distance(coord1: tuple, coord2: tuple) -> float:
    """
    Great-circle distance in metres between two (lat, lon) pairs.
    Used as the A* heuristic — must never overestimate actual path cost.
    """
    R = 6_371_000  # Earth radius in metres
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


SAC_NUMERIC = {
    "hiking":                     1,
    "mountain_hiking":            2,
    "demanding_mountain_hiking":  3,
    "alpine_hiking":              4,
    "demanding_alpine_hiking":    5,
    "difficult_alpine_hiking":    6,
}
