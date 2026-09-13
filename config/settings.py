from pathlib import Path
from decouple import config

import logging as _logging

_logger = _logging.getLogger("db_port_manager")

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-secret-key-not-for-production")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # local apps
    "apps.accounts",
    "apps.monitor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.db_health_middleware.DBHealthMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # WAL mode + safe pragmas: mengurangi risiko korupsi saat crash/unclean
        # shutdown, dan memperbolehkan reader tidak terblokir oleh writer.
        "OPTIONS": {
            "timeout": 30,
        },
    }
}

# Optional backup replica (ApotekApps PostgreSQL). Activated automatically when
# ApotekApps/.env exposes DB_* credentials. Uses db_port_manager for automatic
# port failover: tries 5006 (primary) → 5008 (secondary) → 5007/5009/5432.
try:
    from config.db_port_manager import get_pg_config, update_env_port, _find_env_file

    _env_path = _find_env_file()
    _pg_config = get_pg_config()
    DATABASES["backup_pg"] = _pg_config

    # Persist the detected active port back to .env so subsequent runs
    # and other tools (ensure_db.py, sync_to_postgres) read the same value.
    if _env_path:
        _detected_port = _pg_config.get("PORT", "")
        _current_port = ""
        try:
            for _line in _env_path.read_text().splitlines():
                if _line.strip().startswith("DB_PORT="):
                    _current_port = _line.split("=", 1)[1].strip()
                    break
        except OSError:
            pass
        if _detected_port and _current_port != _detected_port:
            update_env_port(_env_path, _detected_port)
            _logger.warning(
                "DB_PORT changed %s → %s in .env (auto-failover)",
                _current_port or "unset", _detected_port,
            )
except Exception as _e:
    _logger.error("Could not configure backup_pg: %s", _e)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# Auth: local Django users + login with ApotekApps credentials
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "apps.accounts.backends.ApotekAppsBackend",
]

# ApotekApps API config
APOTEK_API_BASE_URL = config("APOTEK_API_BASE_URL", default="http://127.0.0.1:8000/api")
APOTEK_ADMIN_USERNAME = config("APOTEK_ADMIN_USERNAME", default="admin")
APOTEK_ADMIN_PASSWORD = config("APOTEK_ADMIN_PASSWORD", default="admin")

# Session timeout: 8 jam
SESSION_COOKIE_AGE = 28800
