from django.apps import AppConfig


class TrailsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "trails"

    def ready(self):
        # Pre-build the routing graph in a background daemon thread so the
        # first route request doesn't hang waiting for graph construction.
        try:
            from trails.services.routing import warm_up_graph
            warm_up_graph()
        except Exception:
            pass  # DB may not be ready during migrations; safe to skip
