"""
services.py — Core API client dengan retry, rate-limit, dan token management.
"""

import time
import json
import logging
import threading
from django.conf import settings
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import APIRequestLog

logger = logging.getLogger(__name__)

# ── Token cache (per process) ────────────────────────────────────────────────
_token_lock = threading.Lock()
_token_cache: dict = {"access": None, "refresh": None, "expires_at": 0}

BASE_URL = getattr(settings, "APOTEK_API_BASE_URL", "http://127.0.0.1:8000/api")
RATE_LIMIT_PER_MIN = 60  # max requests per minute to ApotekApps
_rate_bucket: dict = {"count": 0, "reset_at": 0}


def _build_session(max_retries: int = 3, backoff: float = 0.5) -> requests.Session:
    """Session dengan retry & exponential backoff untuk 5xx dan network errors."""
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=backoff,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _check_rate_limit():
    """Simple in-memory rate limiter. Raises RuntimeError if over limit."""
    now = time.time()
    if now > _rate_bucket["reset_at"]:
        _rate_bucket["count"] = 0
        _rate_bucket["reset_at"] = now + 60

    _rate_bucket["count"] += 1
    if _rate_bucket["count"] > RATE_LIMIT_PER_MIN:
        wait = _rate_bucket["reset_at"] - now
        raise RuntimeError(f"Rate limit tercapai. Tunggu {wait:.0f} detik.")


def _get_token() -> str | None:
    """Ambil access token, refresh kalau sudah expired."""
    with _token_lock:
        now = time.time()
        # masih valid
        if _token_cache["access"] and now < _token_cache["expires_at"] - 30:
            return _token_cache["access"]

        # coba refresh
        if _token_cache["refresh"]:
            try:
                resp = requests.post(
                    f"{BASE_URL}/auth/refresh/",
                    json={"refresh": _token_cache["refresh"]},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    _token_cache["access"] = data["access"]
                    _token_cache["expires_at"] = now + 86400  # 24 jam
                    return _token_cache["access"]
            except Exception as e:
                logger.warning("Token refresh gagal: %s", e)

        # login ulang
        return _login_and_cache()


def _login_and_cache() -> str | None:
    """Login ke ApotekApps dan cache token."""
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/login/",
            json={
                "username": settings.APOTEK_ADMIN_USERNAME,
                "password": settings.APOTEK_ADMIN_PASSWORD,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _token_cache["access"] = data.get("access")
            _token_cache["refresh"] = data.get("refresh")
            _token_cache["expires_at"] = time.time() + 86400
            return _token_cache["access"]
        logger.error("Login gagal: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("Login error: %s", e)
    return None


def call_api(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    params: dict | None = None,
    max_attempts: int = 3,
    triggered_by: str = "manual",
    save_log: bool = True,
    endpoint_obj=None,
) -> dict:
    """
    Kirim request ke ApotekApps dengan retry + rate-limit + JWT.
    Return dict: {status_code, data, error, response_time_ms, attempt, status}
    """
    _check_rate_limit()

    token = _get_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{BASE_URL}{path}"
    session = _build_session(max_retries=max_attempts)

    start = time.time()
    status_code = None
    response_body = ""
    error_msg = ""
    attempt = 1

    try:
        resp = session.request(
            method.upper(),
            url,
            json=body,
            params=params,
            headers=headers,
            timeout=15,
        )
        status_code = resp.status_code
        # urllib3 retry counts — approximate via response history
        attempt = len(resp.history) + 1
        try:
            response_body = resp.text[:2000]
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:500]}

        elapsed = (time.time() - start) * 1000

        if 200 <= status_code < 300:
            status = APIRequestLog.STATUS_SUCCESS
        elif 400 <= status_code < 500:
            status = APIRequestLog.STATUS_FAIL
            error_msg = response_body[:500]
        else:
            status = APIRequestLog.STATUS_ERROR
            error_msg = response_body[:500]

    except requests.exceptions.ConnectionError as e:
        elapsed = (time.time() - start) * 1000
        data = {}
        error_msg = f"Connection error: {e}"
        status = APIRequestLog.STATUS_ERROR
    except requests.exceptions.Timeout as e:
        elapsed = (time.time() - start) * 1000
        data = {}
        error_msg = f"Timeout: {e}"
        status = APIRequestLog.STATUS_ERROR
    except RuntimeError as e:
        # rate limit
        elapsed = 0
        data = {}
        error_msg = str(e)
        status = APIRequestLog.STATUS_ERROR

    result = {
        "status_code": status_code,
        "data": data,
        "error": error_msg,
        "response_time_ms": round(elapsed, 2),
        "attempt": attempt,
        "status": status,
    }

    if save_log:
        APIRequestLog.objects.create(
            endpoint=endpoint_obj,
            method=method.upper(),
            path=path,
            status_code=status_code,
            status=status,
            response_time_ms=round(elapsed, 2),
            attempt=attempt,
            max_attempts=max_attempts,
            request_body=json.dumps(body or {})[:2000],
            response_body=response_body,
            error_message=error_msg,
            triggered_by=triggered_by,
        )

    return result
