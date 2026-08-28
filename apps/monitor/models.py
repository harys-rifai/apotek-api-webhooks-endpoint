from django.conf import settings
from django.db import models
from django.utils import timezone


class NodeLayout(models.Model):
    """Posisi manual node pada topology smartscape (default setelah di-drag)."""
    node_id = models.CharField(max_length=60, primary_key=True)
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["node_id"]

    def __str__(self):
        return f"{self.node_id} @ ({self.x},{self.y})"


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

    @property
    def health_status(self):
        """Status untuk health-check availability.

        Untuk probe otomatis, `4xx` (client error) berarti endpoint tetap
        terjangkau & merespons — bukan outage. Hanya `5xx`/timeout/connection
        error yang dihitung sebagai kegagalan availability. Sebaliknya `4xx`
        dari body kosong (mis. POST login tanpa payload) adalah ekspektasi,
        bukan indikasi layanan mati.
        """
        if self.status == self.STATUS_ERROR:
            return "error"
        if self.status_code and 400 <= self.status_code < 500:
            return "client_error"
        return self.status  # success / fail


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


class AIConfig(models.Model):
    """Configuration for the OpenAI-compatible AI router used by the chatbot.

    Mirip dengan ApotekApps: satu baris aktif, menyimpan base_url router
    (mis. LiteLLM / OpenAI-compatible), api_key, dan model. Chatbot non-aktif
    bila ``enabled=False`` atau kredensial kosong.
    """

    api_key = models.CharField(max_length=255, blank=True, default="")
    base_url = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Base URL router AI (OpenAI-compatible), mis. http://localhost:20128/v1",
    )
    model = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Nama router / model (mis. gpt-4o, atau nama router LiteLLM).",
    )
    enabled = models.BooleanField(default=False)
    system_prompt = models.TextField(
        blank=True, default=(
            "You are the AI assistant for 'OrchestrationApps', a monitoring "
            "dashboard for the ApotekApps pharmacy backend (API, database, redis, "
            "nginx, webhooks). Answer in the user's language. Help with using the "
            "dashboard, interpreting metrics, and troubleshooting incidents."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI Config"
        verbose_name_plural = "AI Config"

    def __str__(self):
        return f"AIConfig(enabled={self.enabled}, model={self.model or '-'})"

    @classmethod
    def get_active(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj

    def mask_key(self):
        if not self.api_key:
            return ""
        k = self.api_key
        if len(k) <= 8:
            return "****" + k[-2:]
        return k[:6] + "****" + k[-4:]


class ConnectionConfig(models.Model):
    """Pengaturan koneksi datastore & AI yang bisa diedit dari menu Config.

    Satu baris aktif (singleton). Field bersifat opsional — bila kosong, sistem
    akan fallback ke nilai dari ApotekApps/.env agar kompatibel dengan behaviour
    lama.
    """

    # SQLite (database Monitor sendiri)
    sqlite_path = models.CharField(
        max_length=512, blank=True, default="",
        help_text="Path file db.sqlite3 Monitor. Kosongkan untuk default.",
    )

    # PostgreSQL (replica ApotekApps)
    pg_host = models.CharField(max_length=255, blank=True, default="")
    pg_port = models.IntegerField(blank=True, null=True)
    pg_name = models.CharField(max_length=255, blank=True, default="")
    pg_user = models.CharField(max_length=255, blank=True, default="")
    pg_password = models.CharField(max_length=255, blank=True, default="")

    # Redis
    redis_url = models.CharField(
        max_length=512, blank=True, default="",
        help_text="redis://[:password@]host:port/db — kosongkan untuk default.",
    )

    # AI (sinkron dengan AIConfig)
    ai_enabled = models.BooleanField(default=False)
    ai_base_url = models.CharField(max_length=255, blank=True, default="")
    ai_model = models.CharField(max_length=100, blank=True, default="")
    ai_api_key = models.CharField(max_length=255, blank=True, default="")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Connection Config"
        verbose_name_plural = "Connection Config"

    def __str__(self):
        return f"ConnectionConfig(updated={self.updated_at:%Y-%m-%d %H:%M})"

    @classmethod
    def get_active(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj

    def mask_pg_password(self):
        if not self.pg_password:
            return ""
        k = self.pg_password
        if len(k) <= 4:
            return "****"
        return k[:2] + "****" + k[-2:]

    def mask_redis_password(self):
        from urllib.parse import urlparse, unquote
        if not self.redis_url:
            return ""
        parsed = urlparse(self.redis_url)
        if not parsed.password:
            return ""
        k = unquote(parsed.password)
        if len(k) <= 4:
            return "****"
        return k[:2] + "****" + k[-2:]

    def mask_ai_key(self):
        if not self.ai_api_key:
            return ""
        k = self.ai_api_key
        if len(k) <= 8:
            return "****" + k[-2:]
        return k[:6] + "****" + k[-4:]


class AIChatLog(models.Model):
    """Log interaksi dengan AI chatbot Monitor."""

    TYPE_CHAT = "chat"
    TYPE_ANALYSIS = "analysis"
    TYPE_CHOICES = [
        (TYPE_CHAT, "Chatbot"),
        (TYPE_ANALYSIS, "Analisis"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="monitor_ai_chat_logs",
    )
    chat_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_CHAT)
    role = models.CharField(max_length=20, default="user")  # user / assistant
    content = models.TextField()
    session_id = models.CharField(max_length=80, blank=True, default="")
    source = models.CharField(max_length=40, blank=True, default="chatbot_widget")
    model = models.CharField(max_length=100, blank=True, default="")
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AI Chat Log"
        verbose_name_plural = "AI Chat Logs"

    def __str__(self):
        return f"[{self.chat_type}] {self.role}: {self.content[:40]}"
