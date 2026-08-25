from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("endpoints/", views.endpoint_list, name="endpoint_list"),
    path("endpoints/<int:pk>/", views.endpoint_detail, name="endpoint_detail"),
    path("logs/", views.log_list, name="log_list"),
    path("webhooks/", views.webhook_list, name="webhook_list"),
    path("architecture/", views.architecture_view, name="architecture"),
    path("topology/", views.topology_view, name="topology"),
    path("deliveries/", views.delivery_list, name="delivery_list"),
    # AJAX / API
    path("api/ping/<int:pk>/", views.api_ping, name="api_ping"),
    path("api/stats/", views.api_stats_json, name="api_stats_json"),
    path("api/activity/", views.api_activity_json, name="api_activity_json"),
    path("api/topology/", views.api_topology_json, name="api_topology_json"),
    # Webhook receiver (dari ApotekApps)
    path("webhook/receive/", views.webhook_receiver, name="webhook_receiver"),
]
