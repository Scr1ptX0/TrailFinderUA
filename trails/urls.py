from django.urls import path
from . import views

urlpatterns = [
    path("",                views.home,          name="home"),
    path("trails/",         views.trail_list,    name="trail-list"),
    path("trails/<int:pk>/", views.trail_detail, name="trail-detail"),
    path("route-builder/",  views.route_builder, name="route-builder"),
]
