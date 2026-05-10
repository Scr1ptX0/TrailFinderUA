"""
Graph-based trail routing using NetworkX + GeoDjango spatial queries.

Usage:
    graph = TrailGraph()
    graph.build_from_db()
    geojson_line = graph.find_route(
        start_point=(48.2, 23.5),
        end_point=(48.3, 23.6),
        weights={"w1": 1.0, "w2": 1.5, "w3": 1.0},
    )
"""
from __future__ import annotations

import logging
from typing import List, Tuple, Dict, Optional

import networkx as nx
from django.contrib.gis.geos import Point

from trails.utils import haversine_distance, SAC_NUMERIC

logger = logging.getLogger(__name__)

# Type aliases
Coord = Tuple[float, float]   # (lat, lon)
Weights = Dict[str, float]


class RouteNotFound(Exception):
    pass


class TrailGraph:
    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()
        # node_id (TrailNode pk) → (lat, lon)
        self._coords: Dict[int, Coord] = {}

    # ------------------------------------------------------------------
    # Build graph
    # ------------------------------------------------------------------

    def build_from_db(
        self,
        weights: Optional[Weights] = None,
    ) -> None:
        """
        Load all TrailNodes from the DB, build directed edges between
        consecutive nodes along each trail.

        Edge cost formula:
            cost = w1 * segment_dist_m + w2 * elevation_diff_m + w3 * sac_numeric
        """
        from trails.models import Trail, TrailNode

        if weights is None:
            weights = {"w1": 1.0, "w2": 1.5, "w3": 1.0}

        w1, w2, w3 = weights["w1"], weights["w2"], weights["w3"]

        self.G.clear()
        self._coords.clear()

        # Fetch all nodes ordered by trail + index, with sac_scale via select_related
        nodes = (
            TrailNode.objects.select_related("trail")
            .order_by("trail_id", "node_index")
        )

        # Group by trail
        trail_nodes: Dict[int, list] = {}
        for node in nodes:
            trail_nodes.setdefault(node.trail_id, []).append(node)
            lat = node.geom.y
            lon = node.geom.x
            self._coords[node.pk] = (lat, lon)
            self.G.add_node(node.pk, lat=lat, lon=lon, elevation=node.elevation_m)

        # Add edges
        for trail_id, node_list in trail_nodes.items():
            sac = SAC_NUMERIC.get(node_list[0].trail.sac_scale, 1)
            for i in range(len(node_list) - 1):
                a = node_list[i]
                b = node_list[i + 1]
                coord_a = self._coords[a.pk]
                coord_b = self._coords[b.pk]
                dist_m = haversine_distance(coord_a, coord_b)
                elev_diff = max(0.0, b.elevation_m - a.elevation_m)  # only uphill penalised
                cost = w1 * dist_m + w2 * elev_diff + w3 * sac * 100
                # Bidirectional — downhill is cheaper
                self.G.add_edge(a.pk, b.pk, cost=cost, trail_id=trail_id)
                down_cost = w1 * dist_m + w3 * sac * 100  # no uphill penalty going back
                self.G.add_edge(b.pk, a.pk, cost=down_cost, trail_id=trail_id)

        logger.info(
            "TrailGraph built: %d nodes, %d edges",
            self.G.number_of_nodes(),
            self.G.number_of_edges(),
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _nearest_node(self, lat: float, lon: float) -> int:
        """Return the graph node pk closest to (lat, lon) via in-memory haversine scan."""
        if not self._coords:
            raise RouteNotFound("Graph is empty — run build_from_db() first.")
        return min(
            self._coords,
            key=lambda pk: haversine_distance((lat, lon), self._coords[pk]),
        )

    def find_route(
        self,
        start_point: Coord,
        end_point: Coord,
        weights: Optional[Weights] = None,
    ) -> dict:
        """
        Run A* between nearest nodes to start/end.

        Returns a GeoJSON-compatible dict with a LineString geometry
        and summary properties.

        Raises RouteNotFound if no path exists.
        """
        if self.G.number_of_nodes() == 0:
            self.build_from_db(weights=weights)

        start_pk = self._nearest_node(*start_point)
        end_pk   = self._nearest_node(*end_point)

        def heuristic(u, v):
            return haversine_distance(self._coords[u], self._coords[v])

        try:
            path_pks: List[int] = nx.astar_path(
                self.G, start_pk, end_pk,
                heuristic=heuristic,
                weight="cost",
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            raise RouteNotFound(str(exc)) from exc

        # Build coordinate list [lon, lat] for GeoJSON
        coordinates = [
            [self._coords[pk][1], self._coords[pk][0]]   # [lon, lat]
            for pk in path_pks
        ]

        total_dist_m = sum(
            haversine_distance(self._coords[path_pks[i]], self._coords[path_pks[i + 1]])
            for i in range(len(path_pks) - 1)
        )

        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
            "properties": {
                "node_count": len(path_pks),
                "distance_km": round(total_dist_m / 1000, 3),
            },
        }


# Module-level singleton — rebuilt per request (stateless in production).
# For production use, cache this in Django's cache framework.
_trail_graph: Optional[TrailGraph] = None


def get_trail_graph() -> TrailGraph:
    global _trail_graph
    if _trail_graph is None:
        _trail_graph = TrailGraph()
        _trail_graph.build_from_db()
    return _trail_graph


def invalidate_trail_graph() -> None:
    global _trail_graph
    _trail_graph = None
