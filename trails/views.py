"""
HTML views rendered by Django Templates + HTMX.
"""
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from .models import Trail, POI, TrailReview
from .serializers import TrailListSerializer, POISerializer
from .utils import estimate_time

# SAC → Leaflet color mapping exposed to templates
SAC_COLORS = {
    "hiking":                     "#4caf50",  # T1 green
    "mountain_hiking":             "#ffeb3b",  # T2 yellow
    "demanding_mountain_hiking":   "#ff9800",  # T3 orange
    "alpine_hiking":               "#f44336",  # T4 red
    "demanding_alpine_hiking":     "#b71c1c",  # T5 dark red
    "difficult_alpine_hiking":     "#880e4f",  # T6 purple-red
}


def home(request):
    trails_qs = Trail.objects.filter(is_active=True)[:100]
    # Serialize trails as GeoJSON for Leaflet
    serializer   = TrailListSerializer(trails_qs, many=True)
    trails_geojson = json.dumps({
        "type": "FeatureCollection",
        "features": serializer.data["features"],
    })
    pois_qs     = POI.objects.all()[:200]
    poi_serial  = POISerializer(pois_qs, many=True)
    pois_geojson = json.dumps({
        "type": "FeatureCollection",
        "features": poi_serial.data["features"],
    })
    return render(request, "trails/home.html", {
        "trails_geojson": trails_geojson,
        "pois_geojson":   pois_geojson,
        "sac_colors":     json.dumps(SAC_COLORS),
        "sac_choices":    Trail.SAC_CHOICES,
    })


def trail_list(request):
    """
    Filterable trail list.  HTMX POSTs to this same view and only gets the
    <div id="trail-cards"> partial back.
    """
    qs = Trail.objects.filter(is_active=True)

    sac      = request.GET.get("sac_scale", "")
    max_dist = request.GET.get("max_distance", "")
    max_elev = request.GET.get("max_elevation", "")

    if sac:
        qs = qs.filter(sac_scale=sac)
    if max_dist:
        try:
            qs = qs.filter(distance_km__lte=float(max_dist))
        except ValueError:
            pass
    if max_elev:
        try:
            qs = qs.filter(elevation_gain_m__lte=int(max_elev))
        except ValueError:
            pass

    paginator = Paginator(qs, 12)
    page      = paginator.get_page(request.GET.get("page", 1))

    ctx = {
        "page":       page,
        "sac_choices": Trail.SAC_CHOICES,
        "sac_colors":  SAC_COLORS,
        "filters": {
            "sac_scale":    sac,
            "max_distance": max_dist,
            "max_elevation": max_elev,
        },
    }

    # HTMX partial response
    if request.headers.get("HX-Request"):
        return render(request, "trails/_trail_cards.html", ctx)

    return render(request, "trails/list.html", ctx)


def trail_detail(request, pk):
    trail = get_object_or_404(Trail, pk=pk, is_active=True)
    nearby_pois = trail.nearby_pois(radius_m=500)
    reviews     = trail.reviews.select_related("user").all()
    saved = (
        request.user.is_authenticated
        and request.user.saved_trails.filter(pk=pk).exists()
    )
    trail_geojson = json.dumps({
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": list(trail.geom.coords)},
        "properties": {"name": trail.name, "sac_scale": trail.sac_scale},
    })
    pois_geojson = json.dumps({
        "type": "FeatureCollection",
        "features": POISerializer(nearby_pois, many=True).data["features"],
    })
    return render(request, "trails/detail.html", {
        "trail":          trail,
        "trail_geojson":  trail_geojson,
        "pois_geojson":   pois_geojson,
        "nearby_pois":    nearby_pois,
        "reviews":        reviews,
        "saved":          saved,
        "estimated_time": estimate_time(trail.distance_km, trail.elevation_gain_m),
        "sac_color":      SAC_COLORS.get(trail.sac_scale, "#9e9e9e"),
        "sac_colors":     json.dumps(SAC_COLORS),
    })


def route_builder(request):
    return render(request, "route_builder.html", {
        "sac_colors": json.dumps(SAC_COLORS),
    })
