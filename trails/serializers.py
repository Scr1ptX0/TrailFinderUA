from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer, GeometrySerializerMethodField
from rest_framework_gis.fields import GeometryField

from .models import Trail, POI, TrailReview
from .utils import estimate_time


# ---------------------------------------------------------------------------
# Trail serializers
# ---------------------------------------------------------------------------

class TrailListSerializer(GeoFeatureModelSerializer):
    """Minimal representation for FeatureCollection list responses."""
    estimated_time_h = serializers.SerializerMethodField()
    sac_label        = serializers.CharField(source="get_sac_scale_display", read_only=True)

    class Meta:
        model  = Trail
        geo_field = "geom"
        fields = [
            "id", "name", "sac_scale", "sac_label",
            "distance_km", "elevation_gain_m", "surface",
            "colour", "highway_type", "is_active", "estimated_time_h",
        ]

    def get_estimated_time_h(self, obj):
        return round(estimate_time(obj.distance_km, obj.elevation_gain_m), 2)


class POISerializer(GeoFeatureModelSerializer):
    poi_label = serializers.CharField(source="get_poi_type_display", read_only=True)

    class Meta:
        model  = POI
        geo_field = "geom"
        fields = ["id", "name", "poi_type", "poi_label", "description"]


class TrailDetailSerializer(GeoFeatureModelSerializer):
    estimated_time_h = serializers.SerializerMethodField()
    sac_label        = serializers.CharField(source="get_sac_scale_display", read_only=True)
    nearby_pois      = serializers.SerializerMethodField()

    class Meta:
        model  = Trail
        geo_field = "geom"
        fields = [
            "id", "name", "sac_scale", "sac_label",
            "distance_km", "elevation_gain_m", "surface",
            "description", "is_active", "estimated_time_h",
            "nearby_pois",
        ]

    def get_estimated_time_h(self, obj):
        return round(estimate_time(obj.distance_km, obj.elevation_gain_m), 2)

    def get_nearby_pois(self, obj):
        pois = obj.nearby_pois(radius_m=500)
        return POISerializer(pois, many=True).data


# ---------------------------------------------------------------------------
# Review serializers
# ---------------------------------------------------------------------------

class TrailReviewSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model  = TrailReview
        fields = ["id", "user", "rating", "comment", "photo", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

    def validate_rating(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value

    def create(self, validated_data):
        trail   = self.context["trail"]
        user    = self.context["request"].user
        review, created = TrailReview.objects.update_or_create(
            user=user, trail=trail,
            defaults=validated_data,
        )
        return review


# ---------------------------------------------------------------------------
# POI nearby (flat, not GeoFeature — used for nearby query endpoint)
# ---------------------------------------------------------------------------

class POINearbySerializer(GeoFeatureModelSerializer):
    poi_label    = serializers.CharField(source="get_poi_type_display", read_only=True)
    distance_m   = serializers.FloatField(read_only=True)   # annotated in view

    class Meta:
        model  = POI
        geo_field = "geom"
        fields = ["id", "name", "poi_type", "poi_label", "description", "distance_m"]
