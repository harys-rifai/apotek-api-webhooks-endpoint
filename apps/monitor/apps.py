from django.apps import AppConfig


class MonitorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.monitor"
    label = "monitor"
    verbose_name = "API Monitor"
