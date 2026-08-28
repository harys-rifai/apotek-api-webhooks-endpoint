from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.db import connections


def _configure_sqlite(sender, connection, **kwargs):
    # Jalankan PRAGMA keamanan sekali per koneksi baru (WAL mengurangi
    # risiko korupsi saat crash; busy_timeout mencegah 'database is locked').
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cur:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")


class MonitorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.monitor"
    label = "monitor"
    verbose_name = "API Monitor"

    def ready(self):
        connection_created.connect(_configure_sqlite, dispatch_uid="monitor_sqlite_pragmas")
