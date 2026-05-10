"""
Graph-based routing: builds directly from Trail.geom (no TrailNode queries).

Performance design:
  - Samples Trail geometries at controlled density (roads 100 m, trails 30 m)
    → ~500K nodes instead of millions of TrailNode rows
  - scipy.cKDTree for O(log N) nearest-node lookup
  - cKDTree radius queries for O(N log N) endpoint stitching
  - Shared coordinate keys (rounded to ~1 m) unify road intersections
  - Background daemon thread pre-builds the graph at server startup
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from trails.utils import haversine_distance, SAC_NUMERIC

logger = logging.getLogger(__name__)

Coord   = Tuple[float, float]   # (lat, lon)
Weights = Dict[str, float]

MAX_SNAP_DIST_M = 5_000     # 5 km — with roads, anything is reachable
JOIN_TRAIL_M    = 100.0     # stitch trail endpoints within 100 m
JOIN_ROAD_M     = 8.0       # road intersections (shared coords ≤ 8 m)
ROAD_STEP_M     = 100.0     # sample road geometry every 100 m
TRAIL_STEP_M    = 30.0      # sample trail geometry every 30 m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coord_key(lat: float, lon: float) -> Tuple[float, float]:
    """Round to ~1 m precision so shared road corners hash identically."""
    return (round(lat, 5), round(lon, 5))


def _sample_line(coords: List[Tuple[float, float]], step_m: float) -> List[Tuple[float, float]]:
    """
    Return a sub-sampled coordinate list with ~step_m spacing.
    coords: list of (lon, lat) tuples from GEOS geometry.
    Returns: list of (lon, lat), always includes first and last.
    """
    if len(coords) <= 2:
        return list(coords)
    result = [coords[0]]
    accumulated = 0.0
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        d = haversine_distance((lat1, lon1), (lat2, lon2))
        accumulated += d
        if accumulated >= step_m or i == len(coords) - 1:
            result.append(coords[i])
            accumulated = 0.0
    # Always include the last point
    if result[-1] != coords[-1]:
        result.append(coords[-1])
    return result


# ---------------------------------------------------------------------------
# TrailGraph
# ---------------------------------------------------------------------------

class RouteNotFound(Exception):
    pass


class TrailGraph:
    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()
        # node key → (lat, lon)
        self._coords: Dict[Tuple[float, float], Coord] = {}
        self._kdtree: Optional[cKDTree] = None
        self._key_array: Optional[np.ndarray] = None   # parallel array of keys
        self._ready = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_from_db(self) -> None:
        """
        Build routing graph directly from Trail.geom — no TrailNode needed.

        Each trail is sampled at ROAD_STEP_M or TRAIL_STEP_M intervals.
        Coordinate keys are rounded to ~1 m so road intersections
        that share the same OSM node are automatically merged.
        """
        from trails.models import Trail

        logger.info("TrailGraph: loading Trail geometries …")
        self.G.clear()
        self._coords.clear()
        self._ready = False

        trails = list(
            Trail.objects
            .filter(is_active=True)
            .only("id", "sac_scale", "highway_type", "geom")
        )
        if not trails:
            logger.warning("TrailGraph: Trail table is empty — run import_osm_trails.")
            return

        logger.info("TrailGraph: %d trails to process", len(trails))

        # ── 1. Sample each trail and register nodes ──────────────────────
        trail_sampled: List[Tuple[int, str, List[Tuple[float, float]]]] = []
        # (trail_id, highway_type, list of coord_keys)

        for trail in trails:
            step = ROAD_STEP_M if trail.highway_type == "road" else TRAIL_STEP_M
            raw_coords = list(trail.geom.coords)  # [(lon, lat), …]
            sampled    = _sample_line(raw_coords, step)

            keys: List[Tuple[float, float]] = []
            for (lon, lat) in sampled:
                key = _coord_key(lat, lon)
                if key not in self._coords:
                    self._coords[key] = (lat, lon)
                    self.G.add_node(key, lat=lat, lon=lon, elevation=0.0)
                keys.append(key)

            trail_sampled.append((trail.id, trail.highway_type, keys))

        # ── 2. Build KD-tree ──────────────────────────────────────────────
        key_list = list(self._coords.keys())
        lat_arr  = np.array([self._coords[k][0] for k in key_list])
        lon_arr  = np.array([self._coords[k][1] for k in key_list])
        coords_arr      = np.column_stack([lat_arr, lon_arr])
        self._kdtree    = cKDTree(coords_arr)
        self._key_list  = key_list                          # list of tuple keys
        self._key_array = np.column_stack([lat_arr, lon_arr])  # for reference only

        logger.info(
            "TrailGraph: %d unique nodes, building intra-trail edges …",
            len(key_list),
        )

        # Build quick id→trail lookup for sac
        trail_by_id = {t.id: t for t in trails}

        # ── 3. Intra-trail edges ──────────────────────────────────────────
        # Collect endpoints per trail for stitching step
        endpoints: List[Tuple[Tuple[float,float], str, int]] = []
        # (coord_key, highway_type, sac_numeric)

        for trail_id, htype, keys in trail_sampled:
            sac = SAC_NUMERIC.get(trail_by_id[trail_id].sac_scale, 1)
            for i in range(len(keys) - 1):
                ka, kb = keys[i], keys[i + 1]
                dist_m = haversine_distance(self._coords[ka], self._coords[kb])
                self.G.add_edge(ka, kb,
                    dist_m=dist_m, elev_diff=0.0, sac=sac, trail_id=trail_id)
                self.G.add_edge(kb, ka,
                    dist_m=dist_m, elev_diff=0.0, sac=sac, trail_id=trail_id)
            if keys:
                endpoints.append((keys[0],  htype, sac))
                endpoints.append((keys[-1], htype, sac))

        logger.info("TrailGraph: stitching %d endpoints …", len(endpoints))

        # ── 4. Stitch endpoints across trails ────────────────────────────
        JOIN_TRAIL_DEG = JOIN_TRAIL_M / 111_320
        JOIN_ROAD_DEG  = JOIN_ROAD_M  / 111_320

        for ep_key, htype, sac in endpoints:
            lat, lon   = self._coords[ep_key]
            join_deg   = JOIN_ROAD_DEG if htype == "road" else JOIN_TRAIL_DEG
            indices    = self._kdtree.query_ball_point([lat, lon], join_deg)
            for idx in indices:
                other_key = self._key_list[idx]
                if other_key == ep_key:
                    continue
                if self.G.has_edge(ep_key, other_key):
                    continue
                d = haversine_distance((lat, lon), self._coords[other_key])
                self.G.add_edge(ep_key, other_key,
                    dist_m=d, elev_diff=0.0, sac=sac, trail_id=-1)
                self.G.add_edge(other_key, ep_key,
                    dist_m=d, elev_diff=0.0, sac=sac, trail_id=-1)

        self._ready = True
        logger.info(
            "TrailGraph ready: %d nodes, %d edges",
            self.G.number_of_nodes(), self.G.number_of_edges(),
        )

    # ------------------------------------------------------------------
    # Nearest node — O(log N) via KD-tree
    # ------------------------------------------------------------------

    def _nearest_node(self, lat: float, lon: float) -> Tuple[Tuple[float,float], float]:
        if self._kdtree is None or not self._ready:
            raise RouteNotFound("Граф ще не готовий — зачекайте та спробуйте ще раз.")
        _, idx  = self._kdtree.query([lat, lon], k=1)
        key     = self._key_list[idx]
        dist_m  = haversine_distance((lat, lon), self._coords[key])
        return key, dist_m

    # ------------------------------------------------------------------
    # Route finding
    # ------------------------------------------------------------------

    def find_route(
        self,
        start_point: Coord,
        end_point:   Coord,
        weights:     Optional[Weights] = None,
    ) -> dict:
        """A* path between snapped nodes, with dynamic weights."""
        if not self._ready:
            raise RouteNotFound("Граф ще будується, спробуйте за кілька секунд.")

        w1 = (weights or {}).get("w1", 1.0)
        w2 = (weights or {}).get("w2", 1.5)
        w3 = (weights or {}).get("w3", 1.0)

        start_key, snap_start_m = self._nearest_node(*start_point)
        end_key,   snap_end_m   = self._nearest_node(*end_point)

        if snap_start_m > MAX_SNAP_DIST_M:
            raise RouteNotFound(
                f"Точка старту {snap_start_m/1000:.1f} км від найближчої дороги."
            )
        if snap_end_m > MAX_SNAP_DIST_M:
            raise RouteNotFound(
                f"Точка фінішу {snap_end_m/1000:.1f} км від найближчої дороги."
            )
        if start_key == end_key:
            raise RouteNotFound(
                "Обидві точки знаходяться дуже близько — оберіть точки далі одна від одної."
            )

        def edge_cost(u, v, data):
            return w1 * data["dist_m"] + w2 * data["elev_diff"] + w3 * data["sac"] * 100

        def heuristic(u, v):
            return haversine_distance(self._coords[u], self._coords[v])

        try:
            path: List[Tuple[float,float]] = nx.astar_path(
                self.G, start_key, end_key,
                heuristic=heuristic,
                weight=edge_cost,
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            raise RouteNotFound(str(exc)) from exc

        geojson_coords = [
            [self._coords[k][1], self._coords[k][0]]  # [lon, lat] for GeoJSON
            for k in path
        ]
        total_m = sum(
            haversine_distance(self._coords[path[i]], self._coords[path[i + 1]])
            for i in range(len(path) - 1)
        )

        s = self._coords[start_key]
        e = self._coords[end_key]
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": geojson_coords},
            "properties": {
                "node_count":   len(path),
                "distance_km":  round(total_m / 1000, 3),
                "snap_start":   [s[0], s[1]],
                "snap_end":     [e[0], e[1]],
                "snap_start_m": round(snap_start_m),
                "snap_end_m":   round(snap_end_m),
            },
        }


# ---------------------------------------------------------------------------
# Singleton + background warm-up
# ---------------------------------------------------------------------------

_trail_graph: Optional[TrailGraph] = None
_build_lock  = threading.Lock()


def get_trail_graph() -> TrailGraph:
    global _trail_graph
    if _trail_graph is None:
        with _build_lock:
            if _trail_graph is None:
                g = TrailGraph()
                g.build_from_db()
                _trail_graph = g
    return _trail_graph


def invalidate_trail_graph() -> None:
    global _trail_graph
    _trail_graph = None


def warm_up_graph() -> None:
    """Call from AppConfig.ready() — builds graph in background daemon thread."""
    def _build():
        logger.info("Graph warm-up thread started.")
        try:
            get_trail_graph()
        except Exception as exc:
            logger.error("Graph warm-up failed: %s", exc)

    t = threading.Thread(target=_build, daemon=True, name="graph-warmup")
    t.start()
