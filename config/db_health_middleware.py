"""
db_health_middleware.py — Runtime PostgreSQL health check + failover.

On each request that touches `backup_pg`, if the connection is dead the
middleware attempts a failover to the next available port and retries the
request once. If no port is reachable, it logs a warning and lets the
request fail normally (backup_pg is optional — SQLite primary is unaffected).
"""
import logging

from django.db import OperationalError
from django.db import connections

logger = logging.getLogger(__name__)

FAILOVER_PORTS = [5006, 5008, 5007, 5009, 5432]
_MAX_FAILOVER_ATTEMPTS = 1


class DBHealthMiddleware:
    """Catches OperationalError on backup_pg and attempts runtime failover."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        """No-op: we intercept via process_exception + __call__ wrapper."""
        return None

    def process_exception(self, request, exception):
        """If a view raised OperationalError, try failover on backup_pg then retry."""
        if not isinstance(exception, OperationalError):
            return None

        # Only act on backup_pg errors (skip SQLite/default)
        if "backup_pg" not in connections.databases:
            return None

        db_cfg = connections.databases["backup_pg"]
        host = db_cfg.get("HOST", "localhost")
        user = db_cfg.get("USER", "postgres")
        password = db_cfg.get("PASSWORD", "")
        db_name = db_cfg.get("NAME", "postgres")
        current_port = db_cfg.get("PORT", "5006")

        logger.warning(
            "backup_pg on port %s is down, attempting failover...", current_port,
        )

        new_port = self._try_failover_ports(host, user, password, db_name, current_port)
        if new_port is None:
            logger.error("No PostgreSQL port available for failover!")
            return None  # Let Django return the original error

        logger.info("Failover: backup_pg switched to port %d", new_port)
        db_cfg["PORT"] = str(new_port)
        connections["backup_pg"].close_if_unusable_or_obsolete()

        # Retry the request once with the new connection
        try:
            return self.get_response(request)
        except OperationalError:
            logger.error("Failover did not resolve the connection issue.")
            return None  # Let Django handle the error

    def _try_failover_ports(self, host, user, password, db_name, current_port):
        """Try each failover port and return the first that connects."""
        from config.db_port_manager import try_pg_connect

        current_port_int = None
        try:
            current_port_int = int(current_port)
        except (ValueError, TypeError):
            pass

        for port in FAILOVER_PORTS:
            if port == current_port_int:
                continue
            if try_pg_connect(host, port, user, password, db_name, timeout=3):
                # Persist the new port to .env
                try:
                    from config.db_port_manager import update_env_port, _find_env_file
                    env_path = _find_env_file()
                    if env_path:
                        update_env_port(env_path, port)
                except Exception as e:
                    logger.debug("Could not update .env during failover: %s", e)
                return port
        return None
