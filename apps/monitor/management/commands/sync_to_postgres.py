"""
Backup-plan: sinkronkan data Monitor (SQLite) ke PostgreSQL (ApotekApps).

Menyalin tabel Alert, AiInsight, dan NodeLayout ke schema `monitor_backup`
di PostgreSQL lewat alias DATABASES['backup_pg'] (otomatis aktif bila
ApotekApps/.env berisi kredenserial DB_*). Setiap baris di-upsert berdasarkan
`sync_key` stabil sehingga aman dijalankan berkala (cron / manual).

Auto-failover: pada saat connect, command memastikan port PG yang terkonfigurasi
di .env masih hidup. Jika mati, otomatis mencoba port cadangan lainnya
(5006 → 5008 → 5007 → 5009 → 5432) dan memperbarui .env + ConnectionConfig.

Jalankan:
    python manage.py sync_to_postgres            # sinkron sekali
    python manage.py sync_to_postgres --clear    # hapus dulu isi tabel backup
    python manage.py db_sync_config              # detect + sync port to .env & table
"""
import json

from django.core.management.base import BaseCommand
from django.db import connections
from django.utils import timezone

from apps.monitor.models import Alert, AiInsight, NodeLayout


def _using_backup():
    if "backup_pg" not in connections.databases:
        return False
    try:
        import psycopg2  # noqa: F401
    except Exception:
        try:
            import psycopg  # noqa: F401
        except Exception:
            return False
    return True


def _ensure_tables(cur):
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS monitor_backup;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monitor_backup.alert (
            sync_key TEXT PRIMARY KEY,
            level TEXT, title TEXT, message TEXT, source TEXT,
            is_read BOOLEAN, created_at TIMESTAMPTZ
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monitor_backup.ai_insight (
            sync_key TEXT PRIMARY KEY,
            severity TEXT, summary TEXT, details JSONB, metrics JSONB,
            created_at TIMESTAMPTZ
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monitor_backup.node_layout (
            sync_key TEXT PRIMARY KEY,
            node_id TEXT, x DOUBLE PRECISION, y DOUBLE PRECISION,
            updated_at TIMESTAMPTZ
        );
    """)


def _upsert(cur, table, cols, rows):
    if not rows:
        return 0
    col_sql = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    upd = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "sync_key")
    sql = (f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
           f"ON CONFLICT (sync_key) DO UPDATE SET {upd}")
    cur.executemany(sql, rows)
    return len(rows)


class Command(BaseCommand):
    help = "Sinkronkan Alert, AiInsight, NodeLayout dari SQLite ke PostgreSQL (backup)."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true",
                            help="Kosongkan tabel backup sebelum sinkron.")

    def handle(self, *args, **opts):
        if not _using_backup():
            self.stderr.write(
                "Backup PostgreSQL tidak terkonfigurasi. Pastikan ApotekApps/.env "
                "memiliki DB_HOST/DB_NAME/DB_USER/DB_PASSWORD agar alias "
                "DATABASES['backup_pg'] aktif."
            )
            return

        # Verify the configured PG port is reachable; failover if not.
        from config.db_port_manager import try_pg_connect, update_env_port, _find_env_file, DEFAULT_PORTS

        db_cfg = connections.databases["backup_pg"]
        host = db_cfg.get("HOST", "localhost")
        user = db_cfg.get("USER", "postgres")
        password = db_cfg.get("PASSWORD", "")
        db_name = db_cfg.get("NAME", "apotek_pos")
        current_port_str = db_cfg.get("PORT", "5432")
        try:
            current_port = int(current_port_str)
        except (ValueError, TypeError):
            current_port = 5432

        ports_to_try = list(DEFAULT_PORTS)
        if current_port not in ports_to_try:
            ports_to_try.insert(0, current_port)

        connected = False
        for port in ports_to_try:
            if try_pg_connect(host, port, user, password, db_name, timeout=3):
                if port != current_port:
                    self.stdout.write(f"Failover: {current_port} → {port}")
                    db_cfg["PORT"] = str(port)
                    connections["backup_pg"].close_if_unusable_or_obsolete()
                    env_path = _find_env_file()
                    if env_path:
                        update_env_port(env_path, port)
                connected = True
                break

        if not connected:
            self.stderr.write(
                "Tidak dapat terhubung ke PostgreSQL di semua port yang dicoba."
            )
            return

        conn = connections["backup_pg"]
        with conn.cursor() as cur:
            _ensure_tables(cur)

            if opts["clear"]:
                for t in ("alert", "ai_insight", "node_layout"):
                    cur.execute(f"DELETE FROM monitor_backup.{t}")
                self.stdout.write("Tabel backup dikosongkan.")

            # Alerts
            alert_rows = [(
                f"alert:{a.id}", a.level, a.title, a.message, a.source,
                a.is_read, a.created_at,
            ) for a in Alert.objects.all()]
            n_a = _upsert(cur, "monitor_backup.alert",
                          ["sync_key", "level", "title", "message", "source",
                           "is_read", "created_at"], alert_rows)

            # AI Insights
            ai_rows = [(
                f"ai:{r.id}", r.severity, r.summary,
                json.dumps(r.details, default=str), json.dumps(r.metrics, default=str),
                r.created_at,
            ) for r in AiInsight.objects.all()]
            n_i = _upsert(cur, "monitor_backup.ai_insight",
                          ["sync_key", "severity", "summary", "details", "metrics",
                           "created_at"], ai_rows)

            # Node layouts
            nl_rows = [(
                f"nl:{nl.node_id}", nl.node_id, nl.x, nl.y, nl.updated_at,
            ) for nl in NodeLayout.objects.all()]
            n_n = _upsert(cur, "monitor_backup.node_layout",
                          ["sync_key", "node_id", "x", "y", "updated_at"], nl_rows)

            conn.commit()
            self.stdout.write(
                f"Sync selesai -> Alert: {n_a}, AiInsight: {n_i}, NodeLayout: {n_n}."
            )
