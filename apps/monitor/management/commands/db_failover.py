"""
Manual failover checker: verify the active PostgreSQL port and switch if down.

Usage:
  python manage.py db_failover              # check current port, failover if needed
  python manage.py db_failover --list       # list which PG ports are reachable
"""
from django.core.management.base import BaseCommand

from config.db_port_manager import DEFAULT_PORTS, try_pg_connect, update_env_port, _find_env_file


class Command(BaseCommand):
    help = "Check PostgreSQL port health; failover to next available if down."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list", action="store_true",
            help="List reachable PostgreSQL ports and exit.",
        )

    def handle(self, *args, **opts):
        from config.db_port_manager import get_pg_config, get_active_pg_config, sync_to_connection_config
        from apps.monitor.models import ConnectionConfig

        config = get_active_pg_config()
        host = config.get("HOST", "localhost")
        user = config.get("USER", "postgres")
        password = config.get("PASSWORD", "")
        db_name = config.get("NAME", "apotek_pos")
        current_port = config.get("PORT", "5432")

        if opts["list"]:
            self.stdout.write(f"Checking ports: {DEFAULT_PORTS}")
            for port in DEFAULT_PORTS:
                if try_pg_connect(host, port, user, password, db_name, timeout=3):
                    marker = "  <-- active" if str(port) == str(current_port) else ""
                    self.stdout.write(f"  Port {port}: REACHABLE{marker}")
                else:
                    self.stdout.write(f"  Port {port}: down")
            return

        # Check if current port is still alive
        try:
            is_current_up = try_pg_connect(host, int(current_port), user, password, db_name, timeout=3)
        except (ValueError, TypeError):
            is_current_up = False

        if is_current_up:
            self.stdout.write(
                f"PostgreSQL is healthy on port {current_port}. No failover needed."
            )
            return

        # Current port is down — find a working one
        self.stdout.write(
            self.style.WARNING(f"Port {current_port} is down. Searching for standby...")
        )
        failover_done = False
        for port in DEFAULT_PORTS:
            if port == int(current_port) if str(current_port).isdigit() else False:
                continue
            if try_pg_connect(host, port, user, password, db_name, timeout=3):
                self.stdout.write(
                    self.style.SUCCESS(f"Failover: switched to port {port}")
                )
                # Update .env
                env_path = _find_env_file()
                if env_path:
                    update_env_port(env_path, port)
                    self.stdout.write(f"  Updated .env: DB_PORT={port}")

                # Update ConnectionConfig table
                try:
                    cc, _ = ConnectionConfig.objects.using("default").get_or_create(pk=1)
                    cc.pg_host = host
                    cc.pg_port = port
                    cc.pg_name = db_name
                    cc.pg_user = user
                    cc.pg_password = password
                    cc.save()
                    self.stdout.write(f"  Updated ConnectionConfig table: pg_port={port}")
                except Exception as e:
                    self.stderr.write(f"  (Could not update ConnectionConfig: {e})")

                failover_done = True
                break

        if not failover_done:
            self.stderr.write("No reachable PostgreSQL port found!")
