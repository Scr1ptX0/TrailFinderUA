from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Trail, POI, TrailNode, TrailReview


@admin.register(Trail)
class TrailAdmin(GISModelAdmin):
    list_display   = ["name", "sac_scale", "distance_km", "elevation_gain_m", "is_active"]
    list_filter    = ["sac_scale", "is_active", "surface"]
    search_fields  = ["name", "description"]
    readonly_fields = ["distance_km", "created_at", "updated_at"]
    gis_widget_kwargs = {"attrs": {"default_zoom": 8, "default_lon": 23.5, "default_lat": 48.1}}

    # Українські назви колонок в адмінці
    @admin.display(description="Назва")
    def name(self, obj): return obj.name

    class Meta:
        verbose_name        = "Маршрут"
        verbose_name_plural = "Маршрути"


@admin.register(POI)
class POIAdmin(GISModelAdmin):
    list_display  = ["name", "poi_type"]
    list_filter   = ["poi_type"]
    search_fields = ["name", "description"]


@admin.register(TrailNode)
class TrailNodeAdmin(GISModelAdmin):
    list_display = ["trail", "node_index", "elevation_m"]
    list_filter  = ["trail"]
    ordering     = ["trail", "node_index"]


@admin.register(TrailReview)
class TrailReviewAdmin(admin.ModelAdmin):
    list_display   = ["user", "trail", "rating", "created_at"]
    list_filter    = ["rating"]
    search_fields  = ["user__username", "trail__name", "comment"]
    readonly_fields = ["created_at"]
