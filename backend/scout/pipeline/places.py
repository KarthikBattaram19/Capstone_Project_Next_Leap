"""The build-time table of named Bengaluru places a renter can commute to (Task 2.7).

There is no geocoding inside a turn (A3): "I work in Whitefield" is resolved against this
table, and a name that is not in it makes the assistant ask rather than guess.

Two kinds of entry:
- every locality in the bundle, at the MEDIAN of its listings' coordinates. The median, not
  the mean: the sheet's coordinates are not always right, and one listing in the wrong place
  drags a mean with it.
- a handful of well-known work hubs, typed once from OpenStreetMap with a source link. A
  typed hub WINS over a locality of the same name. Measured on 2026-09-09: "Whitefield" has
  two listings in this dataset and one of them sits at 12.9101, 77.5425 — about 22 km west
  of Whitefield — so its computed centre landed in the middle of the city. A sourced
  coordinate for a named place beats a two-point average of unreliable ones.

Run from the repo root after the bundle's listings.json exists:

    backend/.venv/Scripts/python.exe -m scout.pipeline.places ../data/bundle
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median

from scout.domain.listing import ListingRecord

OSM_SEARCH = "https://www.openstreetmap.org/search?query="

# Typed once, from OpenStreetMap. These are the places renters name as "work"; each one
# overrides any computed centre of the same name.
WORK_HUBS: dict[str, tuple[float, float]] = {
    "Whitefield": (12.9698, 77.7500),
    "Electronic City": (12.8452, 77.6602),
    "Manyata Tech Park": (13.0447, 77.6205),
    "MG Road": (12.9756, 77.6068),
}


def build_places(records: list[ListingRecord]) -> dict[str, dict]:
    by_locality: dict[str, list[tuple[float, float]]] = {}
    for r in records:
        if r.coordinates is not None:
            by_locality.setdefault(r.locality, []).append((r.coordinates.lat, r.coordinates.lng))

    places: dict[str, dict] = {}
    for locality, points in sorted(by_locality.items()):
        places[locality] = {
            "lat": round(median(p[0] for p in points), 6),
            "lng": round(median(p[1] for p in points), 6),
            "source": "computed: median of this locality's listing coordinates in the bundle",
        }
    for name, (lat, lng) in WORK_HUBS.items():  # a sourced hub overrides a computed centre
        places[name] = {
            "lat": lat,
            "lng": lng,
            "source": OSM_SEARCH + name.replace(" ", "%20") + "%2C%20Bengaluru",
        }
    return dict(sorted(places.items()))


def main(bundle_dir: str) -> None:
    d = Path(bundle_dir)
    records = [
        ListingRecord.model_validate(x)
        for x in json.loads((d / "listings.json").read_text(encoding="utf-8"))
    ]
    places = build_places(records)
    (d / "places.json").write_text(json.dumps(places, indent=1), encoding="utf-8")
    print(f"wrote {d / 'places.json'}: {len(places)} places")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../data/bundle")
