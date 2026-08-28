from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import MonitorProfile

User = get_user_model()


@admin.register(MonitorProfile)
class MonitorProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "source", "external_id", "synced_at", "created_at"]
    list_filter = ["source"]
    search_fields = ["user__username"]
