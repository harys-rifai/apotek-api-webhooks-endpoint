"""
db_port_manager.py — PostgreSQL port auto-detection & failover.

Tries ports in priority order: 5006 (primary), 5008 (secondary),
5007, 5009, 5432. Updates .env and optionally the ConnectionConfig table
when a different port becomes active.

Usage from settings.py:
    from config.db_port_manager import get_pg_config
    DATABASES["backup_pg"] = get_pg_config()

Usage from run scripts:
    python -c "from config.db_port_manager import main; main()"
    -> detects port, writes .env, prints result
"""
import os
import sys
import socket
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PORTS = [5006, 5008, 5007, 5009, 5432]

DEFAULT_CONFIG = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "apotek_pos",
    "USER": "postgres",
    "PASSWORD": "Password09!",
    "HOST": "localhost",
    "PORT": "5006",
}


def _project_root():
    """Return the project root (parent of config/)."""
    return Path(__file__).resolve().parent.parent


def _find_env_file():
    """Locate the .env file: prefer ApotekApps/.env (sibling project)."""
    root = _project_root()
    candidates = [
        root.parent / "ApotekApps" / ".env",
        root / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _parse_sections(env_path):
    """Parse section-based .env (ApotekApps format with '# PostgreSQLPrimary').

    Returns dict of section_key -> dict_of_values.
    Falls back to 'default' for keys outside any section.
    """
    sections = {"default": {}}
    current = "default"

    try:
        lines = env_path.read_text().splitlines()
    except OSError:
        return sections

    for raw in lines:
        line = raw.strip()
        if line.startswith("#"):
            marker = (
                line[1:]
                .strip()
                .lower()
                .replace("_", "")
                .replace("-", "")
                .replace(" ", "")
            )
            if marker in ("postgresqlprimary", "postgresprimary"):
                current = "primary"
            elif marker in ("postgresqlsecondary", "postgressecondary"):
                current = "secondary"
            else:
                current = None
            if current:
                sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections.setdefault(current, {})[key.strip()] = value.strip()

    return sections


def _parse_env_simple(env_path):
    """Parse plain key=value .env (no sections). Returns merged dict."""
    config = dict(DEFAULT_CONFIG)
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    except OSError:
        pass
    return config


def try_pg_connect(host, port, user, password, dbname="postgres", timeout=3):
    """Test a PostgreSQL connection on (host, port).

    Uses psycopg3 (psycopg) first, falls back to psycopg2, then TCP-only.
    Returns True if the connection succeeded.
    """
    try:
        import psycopg
        conn = psycopg.connect(
            host=host, port=port, user=user, password=password,
            dbname=dbname, connect_timeout=timeout,
        )
        conn.close()
        return True
    except ImportError:
        pass
    except Exception:
        return False

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password,
            dbname=dbname, connect_timeout=timeout,
        )
        conn.close()
        return True
    except ImportError:
        pass
    except Exception:
        return False

    # Last resort: TCP connect check
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, int(port))) == 0
    except Exception:
        return False


def detect_available_port(
    host, user, password,
    dbname="postgres",
    ports=None,
    timeout=3,
):
    """Try each candidate port; return the first that accepts a PG connection.

    Returns the port number (int) or None if none are reachable.
    """
    if ports is None:
        ports = DEFAULT_PORTS
    for port in ports:
        if try_pg_connect(host, port, user, password, dbname, timeout):
            return port
    return None


def _resolve_candidate_ports(sections):
    """Build an ordered candidate-port list from parsed sections.

    Priority: primary port, secondary port, then DEFAULT_PORTS.
    """
    seen = set()
    candidates = []

    for sec_name in ("primary", "secondary"):
        sec = sections.get(sec_name, {})
        port = sec.get("DB_PORT", sec.get("STANDBY_DB_PORT"))
        if port:
            try:
                p = int(port)
                if p not in seen:
                    candidates.append(p)
                    seen.add(p)
            except ValueError:
                pass

    for p in DEFAULT_PORTS:
        if p not in seen:
            candidates.append(p)
            seen.add(p)

    return candidates


def _config_from_section(sections, sec_name):
    """Build a Django DB config dict from a parsed .env section."""
    sec = sections.get(sec_name, {})
    if not sec and sec_name == "default":
        sec = sections.get("default", {}) or dict(DEFAULT_CONFIG)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(sec)
    return cfg


def get_pg_config():
    """Detect the best available PostgreSQL port and return a Django DB config.

    Reads .env (ApotekApps/.env or local .env). Tries each candidate port.
    Falls back to the .env config if no port is reachable.

    Returns dict with keys: ENGINE, NAME, USER, PASSWORD, HOST, PORT.
    """
    env_path = _find_env_file()

    if env_path is None:
        logger.warning("db_port_manager: No .env found, using defaults")
        return dict(DEFAULT_CONFIG)

    sections = _parse_sections(env_path)
    has_primary = bool(sections.get("primary"))

    if has_primary:
        primary = _config_from_section(sections, "primary")
        secondary = _config_from_section(sections, "secondary") if sections.get("secondary") else None
        candidate_ports = _resolve_candidate_ports(sections)

        host = primary.get("HOST", "localhost")
        user = primary.get("USER", "postgres")
        password = primary.get("PASSWORD", "")
        db_name = primary.get("NAME", "apotek_pos")

        detected = detect_available_port(host, user, password, db_name, candidate_ports)
        if detected is None:
            logger.warning("db_port_manager: No PostgreSQL port reachable, using .env config")
            return primary

        # Determine which config to use based on the detected port
        if detected == int(primary.get("PORT", 5006)):
            return primary
        if secondary and detected == int(secondary.get("PORT", 5008)):
            logger.info("Failover: primary port down, using secondary port %d", detected)
            return secondary
        # Detected a port not in primary/secondary — use primary config with new port
        cfg = dict(primary)
        cfg["PORT"] = str(detected)
        logger.info("Failover: using fallback port %d", detected)
        return cfg
    else:
        # Simple .env format
        config = _parse_env_simple(env_path)
        host = config.get("HOST", "localhost")
        user = config.get("USER", "postgres")
        password = config.get("PASSWORD", "")
        db_name = config.get("NAME", "apotek_pos")
        detected = detect_available_port(host, user, password, db_name, DEFAULT_PORTS)
        if detected is not None:
            config["PORT"] = str(detected)
        else:
            logger.warning("db_port_manager: No PostgreSQL port reachable, using .env config")
        return config


def update_env_port(env_path, port):
    """Update DB_PORT=<port> in .env file (idempotent)."""
    env_path = Path(env_path)
    lines = env_path.read_text().splitlines()
    new_lines = []
    found = False
    for line in lines:
        if re.match(r"^\s*DB_PORT=", line):
            new_lines.append(f"DB_PORT={port}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"DB_PORT={port}")
    env_path.write_text("\n".join(new_lines) + "\n")


def sync_to_connection_config():
    """After Django setup, persist active PG config to ConnectionConfig table.

    Called by run scripts and management commands. Gracefully no-ops if
    Django is not configured or the table doesn't exist yet.
    """
    try:
        import django
        if not _is_django_ready():
            return False
        from django.db import transaction
        from apps.monitor.models import ConnectionConfig

        config = get_pg_config()
        with transaction.atomic():
            cc, _ = ConnectionConfig.objects.get_or_create(pk=1)
            cc.pg_host = config.get("HOST", "")
            cc.pg_port = int(config.get("PORT", 5006))
            cc.pg_name = config.get("NAME", "")
            cc.pg_user = config.get("USER", "")
            cc.pg_password = config.get("PASSWORD", "")
            cc.save()
        return True
    except Exception as e:
        logger.debug("sync_to_connection_config skipped: %s", e)
        return False


def get_active_pg_config():
    """Return the active PG config, preferring ConnectionConfig table over .env.

    This implements the `.env <-> table` sync: the table is the source of
    truth once db_sync_config has populated it; otherwise we fall back to
    .env-driven auto-detection.

    Requires Django to be initialized (use outside settings.py).
    """
    try:
        from apps.monitor.models import ConnectionConfig
        active = ConnectionConfig.objects.using("default").first()
        if active and active.pg_port:
            return {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": active.pg_name or "apotek_pos",
                "USER": active.pg_user or "postgres",
                "PASSWORD": active.pg_password or "",
                "HOST": active.pg_host or "localhost",
                "PORT": str(active.pg_port),
            }
    except Exception:
        pass

    # Fallback: use .env-driven detection
    return get_pg_config()


def _is_django_ready():
    try:
        from django.conf import settings
        return hasattr(settings, "DATABASES") and bool(getattr(settings, "DATABASES", None))
    except Exception:
        return False


def main():
    """CLI entry: detect port, update .env, optionally sync to DB table.

    Usage:
        python -c "from config.db_port_manager import main; main()"
        python -c "from config.db_port_manager import main; main()" --sync-db
    """
    env_path = _find_env_file()
    if env_path is None:
        print("WARNING: No .env found. Using defaults.")
        env_path = _project_root() / ".env"

    print(f"Detecting PostgreSQL port...")

    config = get_pg_config()
    detected_port = config.get("PORT", "5432")
    print(f"  Active PostgreSQL port: {detected_port}")

    update_env_port(env_path, detected_port)
    print(f"  Updated .env: DB_PORT={detected_port}")

    if "--sync-db" in sys.argv:
        if sync_to_connection_config():
            print("  Synced to ConnectionConfig table.")
        else:
            print("  (Could not sync to DB — Django not ready or table missing)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
