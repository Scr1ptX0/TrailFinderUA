"""
Management command: import_osm_trails
--------------------------------------
Fetches hiking trails, roads and POIs from OpenStreetMap (Overpass API) for
the full Ukrainian Carpathians bounding box.

Two-pass strategy:
  Pass 1 — tagged hiking trails (sac_scale / colour / osmc:symbol)
  Pass 2 — all other routable ways (path, footway, track, cycleway,
            residential, unclassified, service, tertiary …)
            stored with highway_type so they render differently.

Usage:
    python manage.py import_osm_trails
    python manage.py import_osm_trails --bbox 47.85,22.2,49.0,25.3
    python manage.py import_osm_trails --clear
    python manage.py import_osm_trails --trails-only
    python manage.py import_osm_trails --roads-only
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List

import requests
from django.contrib.gis.geos import LineString, Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from trails.models import POI, Trail, TrailNode
from trails.services.routing import invalidate_trail_graph

logger = logging.getLogger(__name__)

DEFAULT_BBOX = (47.85, 22.2, 49.0, 25.3)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ── Pass 1: marked hiking trails ──────────────────────────────────────────────
TRAIL_QUERY = """\
[out:json][timeout:180];
(
  way["highway"~"^(path|footway|track)$"]["sac_scale"]({s},{w},{n},{e});
  way["highway"~"^(path|footway)$"]["colour"]({s},{w},{n},{e});
  way["highway"~"^(path|footway)$"]["osmc:symbol"]({s},{w},{n},{e});
  node["natural"="spring"]({s},{w},{n},{e});
  node["tourism"="alpine_hut"]({s},{w},{n},{e});
  node["amenity"="shelter"]({s},{w},{n},{e});
  node["tourism"="camp_site"]({s},{w},{n},{e});
  node["tourism"="viewpoint"]({s},{w},{n},{e});
);
out body geom;
"""

# ── Pass 2: all other routable ways (no sac_scale, no colour tag required) ───
ROADS_QUERY = """\
[out:json][timeout:180];
(
  way["highway"="path"]["sac_scale"!~"."]["colour"!~"."]["osmc:symbol"!~"."]({s},{w},{n},{e});
  way["highway"="footway"]["sac_scale"!~"."]["colour"!~"."]["osmc:symbol"!~"."]({s},{w},{n},{e});
  way["highway"="track"]["sac_scale"!~"."]({s},{w},{n},{e});
  way["highway"="cycleway"]({s},{w},{n},{e});
  way["highway"="residential"]({s},{w},{n},{e});
  way["highway"="unclassified"]({s},{w},{n},{e});
  way["highway"="living_street"]({s},{w},{n},{e});
  way["highway"="tertiary"]({s},{w},{n},{e});
);
out body geom;
"""

SAC_MAP: Dict[str, str] = {
    "hiking":                    "hiking",
    "mountain_hiking":           "mountain_hiking",
    "demanding_mountain_hiking": "demanding_mountain_hiking",
    "alpine_hiking":             "alpine_hiking",
    "demanding_alpine_hiking":   "demanding_alpine_hiking",
    "difficult_alpine_hiking":   "difficult_alpine_hiking",
}

OSMC_COLOURS: Dict[str, str] = {
    "red":    "#e53935",
    "blue":   "#1565c0",
    "green":  "#2e7d32",
    "yellow": "#f9a825",
    "black":  "#212121",
    "orange": "#ff6d00",
    "brown":  "#6d4c41",
    "violet": "#6a1b9a",
}

# highway tag → display colour for roads (used when no colour/sac_scale)
HIGHWAY_COLOURS: Dict[str, str] = {
    "path":          "#9e9e9e",
    "footway":       "#9e9e9e",
    "track":         "#795548",
    "cycleway":      "#1565c0",
    "residential":   "#607d8b",
    "unclassified":  "#607d8b",
    "living_street": "#607d8b",
    "service":       "#78909c",
    "tertiary":      "#546e7a",
    "secondary":     "#455a64",
}


def _extract_colour(tags: dict) -> str:
    raw = tags.get("colour", "").strip()
    if raw:
        return raw if raw.startswith("#") else raw.lower()
    osmc = tags.get("osmc:symbol", "").strip()
    if osmc:
        bg = osmc.split(":")[0].lower()
        return OSMC_COLOURS.get(bg, "")
    return ""


def _fetch_overpass(query: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=240,
                headers={"User-Agent": "TrailFinderUA/2.0 (educational project)"},
            )
            if not resp.ok:
                logger.warning("Overpass attempt %d HTTP %d: %s",
                               attempt + 1, resp.status_code, resp.text[:500])
                resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("Overpass attempt %d failed: %s", attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    raise CommandError("All Overpass API attempts failed.")


def _parse_ways(elements: List[dict], highway_type_default: str = "trail") -> List[dict]:
    ways = []
    seen_ids: set = set()
    for el in elements:
        if el["type"] != "way":
            continue
        if el["id"] in seen_ids:
            continue
        seen_ids.add(el["id"])
        coords = [
            (pt["lon"], pt["lat"])
            for pt in el.get("geometry", [])
            if "lat" in pt and "lon" in pt
        ]
        if len(coords) < 2:
            continue
        ways.append({
            "element": el,
            "coords": coords,
            "highway_type_default": highway_type_default,
        })
    return ways


def _parse_poi_nodes(elements: List[dict]) -> List[dict]:
    pois = []
    seen_ids: set = set()
    for el in elements:
        if el["type"] != "node":
            continue
        if el["id"] in seen_ids:
            continue
        seen_ids.add(el["id"])
        tags = el.get("tags", {})
        p_type = None
        if tags.get("natural") == "spring":
            p_type = "water_source"
        elif tags.get("tourism") == "alpine_hut" or tags.get("amenity") == "shelter":
            p_type = "shelter"
        elif tags.get("tourism") == "camp_site":
            p_type = "camping"
        elif tags.get("tourism") == "viewpoint":
            p_type = "viewpoint"
        if p_type is None:
            continue
        pois.append({
            "osm_id":      el["id"],
            "lat":         el["lat"],
            "lon":         el["lon"],
            "poi_type":    p_type,
            "name":        (tags.get("name") or tags.get("name:uk")
                            or tags.get("name:en")
                            or p_type.replace("_", " ").title()),
            "description": tags.get("description", ""),
        })
    return pois


class Command(BaseCommand):
    help = "Import trails, roads and POIs from OpenStreetMap (full Ukrainian Carpathians)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bbox",
            default=",".join(str(v) for v in DEFAULT_BBOX),
            help="south,west,north,east  (default: full Ukrainian Carpathians)",
        )
        parser.add_argument("--clear", action="store_true",
                            help="Delete all existing data before import.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and print stats only, no DB writes.")
        parser.add_argument("--trails-only", action="store_true",
                            help="Import only sac_scale/colour trails (skip roads pass).")
        parser.add_argument("--roads-only", action="store_true",
                            help="Import only roads/paths (skip trails pass).")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        try:
            south, west, north, east = [float(v) for v in options["bbox"].split(",")]
        except ValueError:
            raise CommandError("--bbox must be four floats: south,west,north,east")

        bbox = dict(s=south, w=west, n=north, e=east)

        all_ways: List[dict] = []
        all_pois: List[dict] = []

        do_trails = not options["roads_only"]
        do_roads  = not options["trails_only"]

        if do_trails:
            self.stdout.write(self.style.NOTICE("Pass 1 — fetching hiking trails …"))
            raw = _fetch_overpass(TRAIL_QUERY.format(**bbox))
            els = raw.get("elements", [])
            self.stdout.write(f"  Raw elements: {len(els)}")
            all_ways += _parse_ways(els, highway_type_default="trail")
            all_pois += _parse_poi_nodes(els)

        if do_roads:
            self.stdout.write(self.style.NOTICE("Pass 2 — fetching roads & paths …"))
            raw = _fetch_overpass(ROADS_QUERY.format(**bbox))
            els = raw.get("elements", [])
            self.stdout.write(f"  Raw elements: {len(els)}")
            all_ways += _parse_ways(els, highway_type_default="road")

        self.stdout.write(f"Total ways: {len(all_ways)}, POIs: {len(all_pois)}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry-run — no data written."))
            return

        with transaction.atomic():
            if options["clear"]:
                self.stdout.write(self.style.WARNING("Clearing existing data …"))
                TrailNode.objects.all().delete()
                Trail.objects.all().delete()
                POI.objects.all().delete()

            self._import_trails(all_ways, options["batch_size"])
            if all_pois:
                self._import_pois(all_pois, options["batch_size"])

        invalidate_trail_graph()
        self.stdout.write(self.style.SUCCESS("Import complete."))

    def _import_trails(self, ways: List[dict], batch_size: int) -> None:
        self.stdout.write("Saving ways to DB …")
        node_buf: List[TrailNode] = []
        created = skipped = 0

        for item in ways:
            el     = item["element"]
            tags   = el.get("tags", {})
            coords = item["coords"]
            hw     = tags.get("highway", "path")
            htype  = item["highway_type_default"]

            sac    = SAC_MAP.get(tags.get("sac_scale", "hiking"), "hiking")
            colour = _extract_colour(tags) or HIGHWAY_COLOURS.get(hw, "")
            name   = (tags.get("name") or tags.get("name:uk") or tags.get("name:en")
                      or f"{hw.title()} OSM {el['id']}")

            try:
                geom = LineString(coords, srid=4326)
            except Exception as exc:
                logger.debug("Skipping way %s: %s", el["id"], exc)
                skipped += 1
                continue

            trail = Trail(
                name=name, geom=geom, sac_scale=sac,
                colour=colour, highway_type=htype,
                surface=tags.get("surface", ""),
                description=tags.get("description", ""),
                is_active=True,
            )
            trail.save()
            created += 1

            for idx, (lon, lat) in enumerate(coords):
                node_buf.append(TrailNode(
                    trail=trail, node_index=idx,
                    geom=Point(lon, lat, srid=4326),
                    elevation_m=0.0,
                ))

            if len(node_buf) >= batch_size * 5:
                TrailNode.objects.bulk_create(
                    node_buf, batch_size=batch_size, ignore_conflicts=True)
                node_buf.clear()

        if node_buf:
            TrailNode.objects.bulk_create(
                node_buf, batch_size=batch_size, ignore_conflicts=True)

        self.stdout.write(f"  Ways saved: {created}, skipped: {skipped}")

    def _import_pois(self, poi_nodes: List[dict], batch_size: int) -> None:
        self.stdout.write("Saving POIs …")
        poi_objs = [
            POI(name=p["name"], geom=Point(p["lon"], p["lat"], srid=4326),
                poi_type=p["poi_type"], description=p["description"])
            for p in poi_nodes
        ]
        POI.objects.bulk_create(poi_objs, batch_size=batch_size, ignore_conflicts=True)
        self.stdout.write(f"  POIs saved: {len(poi_objs)}")
