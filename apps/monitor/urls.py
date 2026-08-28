from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("endpoints/", views.endpoint_list, name="endpoint_list"),
    path("endpoints/<int:pk>/", views.endpoint_detail, name="endpoint_detail"),
    path("logs/", views.log_list, name="log_list"),
    path("webhooks/", views.webhook_list, name="webhook_list"),

    path("topology/", views.topology_view, name="topology"),
    path("alerts/", views.alerts_view, name="alerts_page"),
    path("deliveries/", views.delivery_list, name="delivery_list"),
    # AJAX / API
    path("api/ping/<int:pk>/", views.api_ping, name="api_ping"),
    path("api/endpoint/<int:pk>/stats/", views.api_endpoint_stats, name="api_endpoint_stats"),
    path("api/stats/", views.api_stats_json, name="api_stats_json"),
    path("api/activity/", views.api_activity_json, name="api_activity_json"),
    path("api/db-sizes/", views.api_db_sizes, name="api_db_sizes"),
    path("api/db-vacuum/", views.api_db_vacuum, name="api_db_vacuum"),
    path("api/db-sqlite-vacuum/", views.api_db_sqlite_vacuum, name="api_db_sqlite_vacuum"),
    path("api/db-redis-flush/", views.api_db_redis_flush, name="api_db_redis_flush"),
    path("api/topology/", views.api_topology_json, name="api_topology_json"),
    path("api/ai-insight/", views.api_ai_insight, name="api_ai_insight"),
    path("api/ai-chat/", views.api_ai_chat, name="api_ai_chat"),
    path("api/ai-chat/history/", views.api_ai_chat_history, name="api_ai_chat_history"),
    path("api/ai-config/", views.api_ai_config, name="api_ai_config"),
    path("api/backup/sync/", views.api_backup_sync, name="api_backup_sync"),
    path("api/topology/layout/", views.api_topology_layout, name="api_topology_layout"),
    path("api/network/stream/", views.api_network_stream, name="api_network_stream"),
    path("api/alerts/", views.api_alerts_json, name="api_alerts_json"),
    path("api/alert/record/", views.api_alert_record, name="api_alert_record"),
    path("api/alert/mark-read/", views.api_alert_mark_read, name="api_alert_mark_read"),
    # Webhook receiver (dari ApotekApps)
    path("webhook/receive/", views.webhook_receiver, name="webhook_receiver"),
]
