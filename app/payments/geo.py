"""Cities and the distance between them. A payment's place is one of these cities, not an exact location."""
from __future__ import annotations

import math
from functools import lru_cache

CITIES = [
    ("Jaipur", 26.91, 75.79), ("Delhi", 28.61, 77.21), ("Mumbai", 19.08, 72.88), ("Bengaluru", 12.97, 77.59),
    ("Hyderabad", 17.39, 78.49), ("Chennai", 13.08, 80.27), ("Kolkata", 22.57, 88.36), ("Pune", 18.52, 73.86),
    ("Ahmedabad", 23.02, 72.57), ("Lucknow", 26.85, 80.95), ("Patna", 25.59, 85.14), ("Bhopal", 23.26, 77.41),
    ("Indore", 22.72, 75.86), ("Kochi", 9.93, 76.27), ("Guwahati", 26.14, 91.74), ("Chandigarh", 30.73, 76.78),
    ("Nagpur", 21.15, 79.09), ("Surat", 21.17, 72.83), ("Kanpur", 26.45, 80.33), ("Coimbatore", 11.02, 76.96),
    ("Ranchi", 23.34, 85.31), ("Raipur", 21.25, 81.63), ("Bhubaneswar", 20.30, 85.82), ("Dehradun", 30.32, 78.03),
    ("Jodhpur", 26.24, 73.02), ("Varanasi", 25.32, 82.97), ("Agra", 27.18, 78.01), ("Visakhapatnam", 17.69, 83.22),
]
CITY_INDEX = {name.lower(): i for i, (name, _, _) in enumerate(CITIES)}


@lru_cache(maxsize=2048)
def km_between(a: int, b: int) -> float:
    """Distance between two city indexes (great circle)."""
    if a == b:
        return 0.0
    (_, la1, lo1), (_, la2, lo2) = CITIES[a], CITIES[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def city_index(name: str | int | None) -> int | None:
    if name is None:
        return None
    if isinstance(name, int):
        return name if 0 <= name < len(CITIES) else None
    return CITY_INDEX.get(name.strip().lower())


def city_name(index: int | None) -> str:
    return CITIES[index][0] if index is not None and 0 <= index < len(CITIES) else "unknown"
