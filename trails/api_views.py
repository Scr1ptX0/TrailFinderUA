"""
DRF API views — JSON / GeoJSON endpoints consumed by Leaflet and the route builder.
"""
from django.contrib.gis.geos import Point, Polygon
from django.db.models import FloatField
from django.db.models.functions import Cast

from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Trail, POI, TrailReview
from .serializers import (
    TrailListSerializer,
    TrailDetailSerializer,
    TrailReviewSerializer,
    POINearbySerializer,
)
from .services.routing import get_trail_graph, invalidate_trail_graph, RouteNotFound
from .utils import estimate_time


# ---------------------------------------------------------------------------
# Trail list — GET /api/trails/
# ---------------------------------------------------------------------------

class TrailsMapAPIView(generics.ListAPIView):
    """GeoJSON FeatureCollection for map overlays.

    ?type=trail  → only hiking trails (default)
    ?type=road   → only roads/paths
    ?type=all    → everything (heavy!)
    """
    serializer_class   = TrailListSerializer
    permission_classes = [AllowAny]
    pagination_class   = None

    def get_queryset(self):
        layer = self.request.query_params.get("type", "trail")
        qs = Trail.objects.filter(is_active=True)
        if layer == "trail":
            qs = qs.filter(highway_type="trail")
        elif layer == "road":
            qs = qs.filter(highway_type="road")
        return qs


class TrailListAPIView(generics.ListAPIView):
    serializer_class   = TrailListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = Trail.objects.filter(is_active=True)

        layer = self.request.query_params.get("type")
        if layer == "trail":
            qs = qs.filter(highway_type="trail")
        elif layer == "road":
            qs = qs.filter(highway_type="road")

        sac = self.request.query_params.get("sac_scale")
        if sac:
            qs = qs.filter(sac_scale=sac)

        max_dist = self.request.query_params.get("max_distance")
        if max_dist:
            try:
                qs = qs.filter(distance_km__lte=float(max_dist))
            except ValueError:
                pass

        max_elev = self.request.query_params.get("max_elevation")
        if max_elev:
            try:
                qs = qs.filter(elevation_gain_m__lte=int(max_elev))
            except ValueError:
                pass

        bbox = self.request.query_params.get("bbox")
        if bbox:
            try:
                lat1, lon1, lat2, lon2 = [float(v) for v in bbox.split(",")]
                bbox_poly = Polygon.from_bbox((lon1, lat1, lon2, lat2))
                bbox_poly.srid = 4326
                qs = qs.filter(geom__bboverlaps=bbox_poly)
            except (ValueError, TypeError):
                pass

        return qs


# ---------------------------------------------------------------------------
# Trail detail — GET /api/trails/<pk>/
# ---------------------------------------------------------------------------

class TrailDetailAPIView(generics.RetrieveAPIView):
    queryset           = Trail.objects.filter(is_active=True)
    serializer_class   = TrailDetailSerializer
    permission_classes = [AllowAny]


# ---------------------------------------------------------------------------
# Reviews — GET/POST /api/trails/<pk>/reviews/
# ---------------------------------------------------------------------------

class TrailReviewListCreateView(generics.ListCreateAPIView):
    serializer_class   = TrailReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_trail(self):
        return generics.get_object_or_404(Trail, pk=self.kwargs["pk"])

    def get_queryset(self):
        return TrailReview.objects.filter(trail=self.get_trail()).select_related("user")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["trail"] = self.get_trail()
        return ctx

    def perform_create(self, serializer):
        serializer.save()


# ---------------------------------------------------------------------------
# Nearby POIs — GET /api/pois/nearby/?lat=&lon=&radius_m=
# ---------------------------------------------------------------------------

class POINearbyAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            lat      = float(request.query_params["lat"])
            lon      = float(request.query_params["lon"])
            radius_m = float(request.query_params.get("radius_m", 500))
        except (KeyError, ValueError):
            return Response(
                {"detail": "Provide ?lat=&lon= query params (radius_m optional, default 500)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        origin = Point(lon, lat, srid=4326)
        pois = (
            POI.objects
            .filter(geom__dwithin=(origin, radius_m / 111_320))
            .extra(
                select={
                    "distance_m": (
                        "ST_Distance(geom::geography, "
                        "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)"
                    )
                },
                select_params=[lon, lat],
                order_by=["distance_m"],
            )
        )

        serializer = POINearbySerializer(pois, many=True)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Route builder — POST /api/route/build/
# ---------------------------------------------------------------------------

class BuildRouteAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data

        # Validate payload
        try:
            start = tuple(data["start"])   # [lat, lon]
            end   = tuple(data["end"])     # [lat, lon]
            if len(start) != 2 or len(end) != 2:
                raise ValueError
            start = (float(start[0]), float(start[1]))
            end   = (float(end[0]),   float(end[1]))
        except (KeyError, TypeError, ValueError):
            return Response(
                {"detail": "Body must contain start:[lat,lon] and end:[lat,lon]."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_w = data.get("weights", {})
        weights = {
            "w1": float(raw_w.get("w1", 1.0)),
            "w2": float(raw_w.get("w2", 1.5)),
            "w3": float(raw_w.get("w3", 1.0)),
        }

        graph = get_trail_graph()

        try:
            geojson_feature = graph.find_route(start, end, weights=weights)
        except RouteNotFound as exc:
            return Response(
                {"detail": f"No route found: {exc}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        dist_km  = geojson_feature["properties"]["distance_km"]
        time_h   = estimate_time(dist_km, 0)   # elevation unknown at this stage
        geojson_feature["properties"]["estimated_time_h"] = round(time_h, 2)

        return Response(geojson_feature, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Save / unsave trail (AJAX toggle) — POST /api/trails/<pk>/save/
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticatedOrReadOnly])
def toggle_saved_trail(request, pk):
    trail = generics.get_object_or_404(Trail, pk=pk)
    user  = request.user
    if trail in user.saved_trails.all():
        user.saved_trails.remove(trail)
        saved = False
    else:
        user.saved_trails.add(trail)
        saved = True
    return Response({"saved": saved})
