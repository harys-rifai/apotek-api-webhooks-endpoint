from pathlib import Path
from decouple import config

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
    }
}

# Optional backup replica (ApotekApps PostgreSQL). Activated automatically when
# ApotekApps/.env exposes DB_* credentials. Used by `sync_to_postgres`.
try:
    import os as _os
    from decouple import Config as _Cfg, RepositoryEnv as _RepoEnv
    _apps_env = _os.path.join(_os.path.dirname(str(BASE_DIR)), "ApotekApps", ".env")
    if _os.path.exists(_apps_env):
        _c = _Cfg(_RepoEnv(_apps_env))
        DATABASES["backup_pg"] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _c.get("DB_NAME", "apotek_pos"),
            "USER": _c.get("DB_USER", "postgres"),
            "PASSWORD": _c.get("DB_PASSWORD", ""),
            "HOST": _c.get("DB_HOST", "localhost"),
            "PORT": _c.get("DB_PORT", "5432"),
        }
except Exception:
    pass

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

# ApotekApps API config
APOTEK_API_BASE_URL = config("APOTEK_API_BASE_URL", default="http://127.0.0.1:8000/api")
APOTEK_ADMIN_USERNAME = config("APOTEK_ADMIN_USERNAME", default="admin")
APOTEK_ADMIN_PASSWORD = config("APOTEK_ADMIN_PASSWORD", default="admin")

# Session timeout: 8 jam
SESSION_COOKIE_AGE = 28800
