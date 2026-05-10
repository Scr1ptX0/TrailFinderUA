from django.urls import path
from .api_views import (
    TrailListAPIView,
    TrailDetailAPIView,
    TrailReviewListCreateView,
    POINearbyAPIView,
    BuildRouteAPIView,
    toggle_saved_trail,
)

urlpatterns = [
    path("trails/",                     TrailListAPIView.as_view(),          name="api-trail-list"),
    path("trails/<int:pk>/",            TrailDetailAPIView.as_view(),        name="api-trail-detail"),
    path("trails/<int:pk>/reviews/",    TrailReviewListCreateView.as_view(), name="api-trail-reviews"),
    path("trails/<int:pk>/save/",       toggle_saved_trail,                  name="api-trail-save"),
    path("pois/nearby/",                POINearbyAPIView.as_view(),          name="api-pois-nearby"),
    path("route/build/",                BuildRouteAPIView.as_view(),         name="api-route-build"),
]
