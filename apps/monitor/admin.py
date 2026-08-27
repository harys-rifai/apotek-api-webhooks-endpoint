from django.contrib import admin
from .models import APIEndpoint, APIRequestLog, WebhookEvent, Alert, AiInsight, NodeLayout


@admin.register(NodeLayout)
class NodeLayoutAdmin(admin.ModelAdmin):
    list_display = ["node_id", "x", "y", "updated_at"]
    search_fields = ["node_id"]


@admin.register(AiInsight)
class AiInsightAdmin(admin.ModelAdmin):
    list_display = ["severity", "summary", "created_at"]
    list_filter = ["severity"]
    readonly_fields = ["created_at", "details", "metrics"]


@admin.register(APIEndpoint)
class APIEndpointAdmin(admin.ModelAdmin):
    list_display = ["name", "method", "path", "module", "is_active"]
    list_filter = ["module", "is_active", "method"]
    search_fields = ["name", "path"]


@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    list_display = ["method", "path", "status_code", "status", "response_time_ms", "attempt", "triggered_by", "created_at"]
    list_filter = ["status", "method", "triggered_by"]
    search_fields = ["path", "error_message"]
    readonly_fields = ["created_at"]
    date_hierarchy = "created_at"


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["event_type", "source_ip", "status", "received_at"]
    list_filter = ["status", "event_type"]
    readonly_fields = ["received_at", "processed_at"]


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["level", "title", "source", "is_read", "created_at"]
    list_filter = ["level", "source", "is_read"]
    search_fields = ["title", "message"]
    readonly_fields = ["created_at"]
    actions = ["mark_read"]

    def mark_read(self, request, queryset):
        queryset.update(is_read=True)
    mark_read.short_description = "Tandai sudah dibaca"
