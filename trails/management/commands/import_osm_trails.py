"""
Management command: import_osm_trails
--------------------------------------
Fetches hiking trails and POIs from OpenStreetMap (Overpass API) for the
Ukrainian Carpathians bounding box, then bulk-creates Trail, TrailNode and
POI objects.

Usage:
    python manage.py import_osm_trails
    python manage.py import_osm_trails --bbox 47.8,22.1,48.5,24.7
    python manage.py import_osm_trails --clear   # wipe existing data first
    python manage.py import_osm_trails --dry-run # print stats only
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Tuple

import requests
from django.contrib.gis.geos import LineString, Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from trails.models import POI, Trail, TrailNode
from trails.services.routing import invalidate_trail_graph

logger = logging.getLogger(__name__)

DEFAULT_BBOX = (47.8, 22.1, 48.5, 24.7)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Key fix: use "out body geom;" so way elements contain a "geometry" list of
# {lat, lon} objects directly — no separate node-lookup step needed.
# This is valid Overpass QL and avoids the broken "out skt qt;" syntax.
OVERPASS_QUERY_TEMPLATE = """\
[out:json][timeout:180];
(
  way["highway"~"^(path|footway|track)$"]["sac_scale"]({south},{west},{north},{east});
  node["natural"="spring"]({south},{west},{north},{east});
  node["tourism"="alpine_hut"]({south},{west},{north},{east});
  node["tourism"="camp_site"]({south},{west},{north},{east});
  node["tourism"="viewpoint"]({south},{west},{north},{east});
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


def _fetch_overpass(query: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=240,
                headers={"User-Agent": "TrailFinderUA/1.0 (educational project)"},
            )
            if not resp.ok:
                # Log the actual error body so we can diagnose query issues
                logger.warning(
                    "Overpass attempt %d HTTP %d: %s",
                    attempt + 1, resp.status_code, resp.text[:500],
                )
                resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("Overpass attempt %d failed: %s", attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    raise CommandError("All Overpass API attempts failed. Check connectivity.")


def _parse_ways(elements: List[dict]) -> List[dict]:
    """
    Extract way elements using the inline geometry from "out body geom;".
    Each way element has a "geometry" list of {"lat": …, "lon": …} dicts.
    """
    ways = []
    for el in elements:
        if el["type"] != "way":
            continue
        geom_pts = el.get("geometry", [])
        # (lon, lat) tuples — GEOSGeometry / LineString expects (x, y) = (lon, lat)
        coords = [
            (pt["lon"], pt["lat"])
            for pt in geom_pts
            if "lat" in pt and "lon" in pt
        ]
        if len(coords) < 2:
            continue
        ways.append({"element": el, "coords": coords})
    return ways


def _parse_poi_nodes(elements: List[dict]) -> List[dict]:
    pois = []
    for el in elements:
        if el["type"] != "node":
            continue
        tags = el.get("tags", {})
        p_type = None
        if tags.get("natural") == "spring":
            p_type = "water_source"
        elif tags.get("tourism") == "alpine_hut":
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
            "name":        tags.get("name") or tags.get("name:uk") or tags.get("name:en")
                           or p_type.replace("_", " ").title(),
            "description": tags.get("description", ""),
        })
    return pois


class Command(BaseCommand):
    help = "Import hiking trails and POIs from OpenStreetMap into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bbox",
            default=",".join(str(v) for v in DEFAULT_BBOX),
            help="Bounding box: south,west,north,east  (default: Ukrainian Carpathians)",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="Delete all existing Trail, TrailNode and POI rows before import.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Parse and print statistics without writing to the database.",
        )
        parser.add_argument(
            "--batch-size", type=int, default=500,
            help="Bulk-create batch size (default: 500).",
        )

    def handle(self, *args, **options):
        try:
            south, west, north, east = [float(v) for v in options["bbox"].split(",")]
        except ValueError:
            raise CommandError("--bbox must be four floats: south,west,north,east")

        dry_run    = options["dry_run"]
        batch_size = options["batch_size"]

        self.stdout.write(self.style.NOTICE(
            f"Fetching OSM data for bbox ({south},{west},{north},{east}) …"
        ))

        query    = OVERPASS_QUERY_TEMPLATE.format(
            south=south, west=west, north=north, east=east
        )
        raw_data = _fetch_overpass(query)
        elements = raw_data.get("elements", [])

        self.stdout.write(f"  Raw elements received: {len(elements)}")

        ways      = _parse_ways(elements)
        poi_nodes = _parse_poi_nodes(elements)

        self.stdout.write(f"  Ways (trails): {len(ways)}")
        self.stdout.write(f"  POI nodes:     {len(poi_nodes)}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry-run complete — no data written."))
            return

        with transaction.atomic():
            if options["clear"]:
                self.stdout.write(self.style.WARNING("Clearing existing data …"))
                TrailNode.objects.all().delete()
                Trail.objects.all().delete()
                POI.objects.all().delete()

            self._import_trails(ways, batch_size)
            self._import_pois(poi_nodes, batch_size)

        invalidate_trail_graph()
        self.stdout.write(self.style.SUCCESS("Import complete."))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _import_trails(self, ways: List[dict], batch_size: int) -> None:
        self.stdout.write("Importing trails …")
        node_buf: List[TrailNode] = []
        created = skipped = 0

        for item in ways:
            el     = item["element"]
            tags   = el.get("tags", {})
            coords = item["coords"]

            sac  = SAC_MAP.get(tags.get("sac_scale", "hiking"), "hiking")
            name = (
                tags.get("name")
                or tags.get("name:uk")
                or tags.get("name:en")
                or f"Trail OSM {el['id']}"
            )

            try:
                geom = LineString(coords, srid=4326)
            except Exception as exc:
                logger.debug("Skipping way %s: %s", el["id"], exc)
                skipped += 1
                continue

            # Use save() so the distance_km calculation in Trail.save() runs.
            # 303 individual INSERTs is still fast (~0.1 s total on local PG).
            trail = Trail(
                name=name,
                geom=geom,
                sac_scale=sac,
                surface=tags.get("surface", ""),
                description=tags.get("description", ""),
                is_active=True,
            )
            trail.save()   # populates trail.pk and distance_km
            created += 1

            # Build TrailNodes immediately while we have the PK
            for idx, (lon, lat) in enumerate(coords):
                node_buf.append(TrailNode(
                    trail=trail,
                    node_index=idx,
                    geom=Point(lon, lat, srid=4326),
                    elevation_m=0.0,
                ))

            if len(node_buf) >= batch_size * 5:
                TrailNode.objects.bulk_create(
                    node_buf, batch_size=batch_size, ignore_conflicts=True
                )
                node_buf.clear()

        if node_buf:
            TrailNode.objects.bulk_create(
                node_buf, batch_size=batch_size, ignore_conflicts=True
            )

        self.stdout.write(f"  Trails created: {created}, skipped: {skipped}")
        self.stdout.write(f"  TrailNodes saved.")

    def _import_pois(self, poi_nodes: List[dict], batch_size: int) -> None:
        self.stdout.write("Importing POIs …")
        poi_objs = [
            POI(
                name=p["name"],
                geom=Point(p["lon"], p["lat"], srid=4326),
                poi_type=p["poi_type"],
                description=p["description"],
            )
            for p in poi_nodes
        ]
        POI.objects.bulk_create(poi_objs, batch_size=batch_size, ignore_conflicts=True)
        self.stdout.write(f"  POIs created: {len(poi_objs)}")
