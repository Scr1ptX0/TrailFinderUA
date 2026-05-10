from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.gis.db import models as gis_models


class Trail(gis_models.Model):
    SAC_CHOICES = [
        ("hiking",                      "T1 – Піший"),
        ("mountain_hiking",             "T2 – Гірський"),
        ("demanding_mountain_hiking",   "T3 – Вимогливий гірський"),
        ("alpine_hiking",               "T4 – Альпійський"),
        ("demanding_alpine_hiking",     "T5 – Вимогливий альпійський"),
        ("difficult_alpine_hiking",     "T6 – Складний альпійський"),
    ]

    name            = models.CharField(max_length=255)
    geom            = gis_models.LineStringField(srid=4326)
    sac_scale       = models.CharField(max_length=50, choices=SAC_CHOICES, default="hiking")
    distance_km     = models.FloatField(default=0.0)
    elevation_gain_m = models.IntegerField(default=0)
    surface         = models.CharField(max_length=100, blank=True)
    colour          = models.CharField(max_length=30, blank=True, default='')
    highway_type    = models.CharField(max_length=30, blank=True, default='trail')
    description     = models.TextField(blank=True)
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Маршрут"
        verbose_name_plural = "Маршрути"
        indexes = [
            models.Index(fields=["sac_scale"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_sac_scale_display()})"

    @property
    def sac_numeric(self):
        order = {
            "hiking": 1,
            "mountain_hiking": 2,
            "demanding_mountain_hiking": 3,
            "alpine_hiking": 4,
            "demanding_alpine_hiking": 5,
            "difficult_alpine_hiking": 6,
        }
        return order.get(self.sac_scale, 1)

    def save(self, *args, **kwargs):
        if self.geom:
            # Calculate length in km using PostGIS transform to a metric CRS.
            # We compute it here for convenience; a DB signal could also do this.
            from django.contrib.gis.geos import GEOSGeometry
            geom_wgs84 = self.geom
            # Transform to a metric projection (EPSG:32634 — UTM zone 34N covers Carpathians)
            try:
                geom_metric = geom_wgs84.transform(32634, clone=True)
                self.distance_km = round(geom_metric.length / 1000, 3)
            except Exception:
                pass
        super().save(*args, **kwargs)

    def nearby_pois(self, radius_m=500):
        # geom is SRID=4326 (degrees), not geography — convert m → degrees
        return POI.objects.filter(geom__dwithin=(self.geom, radius_m / 111_320))


class POI(gis_models.Model):
    TYPE_CHOICES = [
        ("water_source", "Джерело води"),
        ("shelter",      "Притулок / Хата"),
        ("camping",      "Кемпінг"),
        ("viewpoint",    "Оглядовий майданчик"),
    ]

    name        = models.CharField(max_length=255)
    geom        = gis_models.PointField(srid=4326)
    poi_type    = models.CharField(max_length=50, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name        = "Об'єкт інтересу (POI)"
        verbose_name_plural = "Об'єкти інтересу (POI)"

    def __str__(self):
        return f"{self.name} ({self.get_poi_type_display()})"


class TrailNode(gis_models.Model):
    """Ordered waypoints along a trail, used for graph-based routing."""
    geom       = gis_models.PointField(srid=4326)
    trail      = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name="nodes")
    node_index = models.IntegerField()
    elevation_m = models.FloatField(default=0.0)

    class Meta:
        verbose_name        = "Вузол маршруту"
        verbose_name_plural = "Вузли маршруту"
        ordering = ["trail", "node_index"]
        unique_together = [("trail", "node_index")]

    def __str__(self):
        return f"Вузол {self.node_index} @ {self.trail.name}"


class TrailReview(models.Model):
    user    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="reviews")
    trail   = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name="reviews")
    rating  = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment    = models.TextField(blank=True)
    photo      = models.ImageField(upload_to="trail_photos/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Відгук"
        verbose_name_plural = "Відгуки"
        unique_together = [("user", "trail")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Відгук від {self.user} на {self.trail} — {self.rating}★"
