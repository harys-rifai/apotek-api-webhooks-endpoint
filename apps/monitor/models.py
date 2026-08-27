from django.db import models
from django.utils import timezone


class AiInsight(models.Model):
    """Snapshot hasil analisis cerdas (AI) terhadap kondisi sistem/monitor."""
    SEVERITY_INFO = "info"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"
    SEVERITY_SUCCESS = "success"
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
        (SEVERITY_SUCCESS, "Success"),
    ]

    summary = models.TextField()
    details = models.JSONField(default=list)  # list of {label, value, severity}
    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_INFO
    )
    metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AI Insight"
        verbose_name_plural = "AI Insights"

    def __str__(self):
        return f"AI Insight [{self.severity}] @ {self.created_at:%Y-%m-%d %H:%M}"


class APIEndpoint(models.Model):
    """Daftar endpoint yang dipantau."""
    name = models.CharField(max_length=120)
    method = models.CharField(max_length=10, default="GET")
    path = models.CharField(max_length=255)  # e.g. /auth/login/
    module = models.CharField(max_length=60, default="general")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["module", "name"]

    def __str__(self):
        return f"[{self.method}] {self.path}"


class APIRequestLog(models.Model):
    """Log setiap request yang dikirim ke ApotekApps API."""
    STATUS_SUCCESS = "success"
    STATUS_FAIL = "fail"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAIL, "Fail"),
        (STATUS_ERROR, "Error"),
    ]

    endpoint = models.ForeignKey(
        APIEndpoint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=255)
    status_code = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ERROR)
    response_time_ms = models.FloatField(null=True, blank=True)
    # Retry info
    attempt = models.PositiveSmallIntegerField(default=1)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    # Request / response snapshot
    request_body = models.TextField(blank=True, default="")
    response_body = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    # Meta
    triggered_by = models.CharField(max_length=80, default="manual")  # manual / scheduler / webhook
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["path", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.method}] {self.path} → {self.status_code} ({self.status})"

    @property
    def is_success(self):
        return self.status == self.STATUS_SUCCESS

    @property
    def is_slow(self):
        return self.response_time_ms is not None and self.response_time_ms > 2000


class Alert(models.Model):
    """Alert/notification tersimpan (mis. perubahan status node topologi)."""
    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_CRITICAL = "critical"
    LEVEL_SUCCESS = "success"
    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_WARNING, "Warning"),
        (LEVEL_CRITICAL, "Critical"),
        (LEVEL_SUCCESS, "Success"),
    ]

    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default="")
    source = models.CharField(max_length=60, default="topology",
                              help_text="Asal alert, mis. topology / monitor")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["is_read", "created_at"])]

    def __str__(self):
        return f"[{self.level}] {self.title}"

    @property
    def icon(self):
        return {
            self.LEVEL_INFO: "fa-circle-info",
            self.LEVEL_WARNING: "fa-triangle-exclamation",
            self.LEVEL_CRITICAL: "fa-circle-xmark",
            self.LEVEL_SUCCESS: "fa-circle-check",
        }.get(self.level, "fa-bell")


class WebhookEvent(models.Model):
    """Event yang diterima dari webhook ApotekApps."""
    STATUS_RECEIVED = "received"
    STATUS_PROCESSED = "processed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_FAILED, "Failed"),
    ]

    event_type = models.CharField(max_length=80)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    payload = models.TextField(default="{}")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RECEIVED)
    error_message = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} [{self.status}] @ {self.received_at:%Y-%m-%d %H:%M}"
