from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("endpoints/", views.endpoint_list, name="endpoint_list"),
    path("endpoints/<int:pk>/", views.endpoint_detail, name="endpoint_detail"),
    path("logs/", views.log_list, name="log_list"),
    path("webhooks/", views.webhook_list, name="webhook_list"),
    # AJAX / API
    path("api/ping/<int:pk>/", views.api_ping, name="api_ping"),
    path("api/stats/", views.api_stats_json, name="api_stats_json"),
    # Webhook receiver (dari ApotekApps)
    path("webhook/receive/", views.webhook_receiver, name="webhook_receiver"),
]
