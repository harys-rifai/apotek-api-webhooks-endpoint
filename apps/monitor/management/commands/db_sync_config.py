"""
Sync .env PostgreSQL settings to the ConnectionConfig table with auto port
detection.

Flow:
  1. Read .env (ApotekApps/.env or local .env) for DB_* credentials.
  2. Probe candidate ports (5006 → 5008 → 5007 → 5009 → 5432).
  3. Pick the first port that accepts a PostgreSQL connection.
  4. Update both .env (DB_PORT=) and ConnectionConfig table.

Usage:
  python manage.py db_sync_config              # detect + sync + print
  python manage.py db_sync_config --force      # re-detect even if current port works
  python manage.py db_sync_config --dry-run     # detect only, no writes
"""
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from config.db_port_manager import (
    get_pg_config,
    update_env_port,
    _find_env_file,
    detect_available_port,
    try_pg_connect,
    DEFAULT_PORTS,
)


class Command(BaseCommand):
    help = "Detect available PostgreSQL port and sync config to .env + ConnectionConfig table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Re-detect even if the currently configured port is reachable.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Detect and print only; do not write to .env or DB.",
        )

    def handle(self, *args, **opts):
        from apps.monitor.models import ConnectionConfig

        env_path = _find_env_file()
        if env_path is None:
            self.stderr.write("No .env file found. Nothing to sync.")
            return

        config = get_pg_config()
        detected_port = config.get("PORT", "5432")
        host = config.get("HOST", "localhost")
        user = config.get("USER", "postgres")
        password = config.get("PASSWORD", "")
        db_name = config.get("NAME", "apotek_pos")

        # Check current .env port
        current_env_port = ""
        try:
            for line in env_path.read_text().splitlines():
                if line.strip().startswith("DB_PORT="):
                    current_env_port = line.split("=", 1)[1].strip()
                    break
        except OSError:
            pass

        # Check current ConnectionConfig port
        current_table_port = ""
        try:
            active = ConnectionConfig.objects.using("default").first()
            if active and active.pg_port:
                current_table_port = str(active.pg_port)
        except Exception as e:
            self.stderr.write(f"(Could not read ConnectionConfig: {e})")

        # If --force is not set and the current port already works, skip
        if not opts["force"] and current_env_port:
            try:
                if int(current_env_port) in DEFAULT_PORTS and try_pg_connect(
                    host, int(current_env_port), user, password, db_name, timeout=3
                ):
                    self.stdout.write(
                        f"Current port {current_env_port} is reachable. "
                        f"Use --force to re-detect."
                    )
                    return
            except ValueError:
                pass

        self.stdout.write(
            f"Detected PostgreSQL port: {detected_port} (was: .env={current_env_port}, "
            f"table={current_table_port})"
        )

        if opts["dry_run"]:
            self.stdout.write("(dry-run: no writes)")
            return

        # Update .env
        if detected_port != current_env_port:
            update_env_port(env_path, detected_port)
            self.stdout.write(f"  Updated .env: DB_PORT={detected_port}")
        else:
            self.stdout.write(f"  .env DB_PORT already = {detected_port}")

        # Sync to ConnectionConfig table
        try:
            with transaction.atomic(using="default"):
                cc, created = ConnectionConfig.objects.get_or_create(pk=1)
                cc.pg_host = config.get("HOST", "localhost")
                cc.pg_port = int(detected_port) if detected_port else 5006
                cc.pg_name = config.get("NAME", "apotek_pos")
                cc.pg_user = config.get("USER", "postgres")
                cc.pg_password = config.get("PASSWORD", "")
                cc.save()
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action} ConnectionConfig: pg_port={detected_port}")
        except Exception as e:
            self.stderr.write(f"  Could not sync to ConnectionConfig (table may need migration): {e}")
