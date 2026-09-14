"""Middleware: show a maintenance splash screen when maintenance mode is active.

Two modes of operation:

1. **Same-database mode** (port 8090 — ApotekMonitor): checks the
   ``MaintenanceMode`` model directly.

2. **File-based mode** (port 8000 — ApotekApps / POS Apotek, a separate service):
   reads ``maintenance_state.json`` written by the monitoring app so the state
   is shared across services without a shared DB.

The splash template is rendered instead of the requested view, so the page
cannot be closed or bypassed via URL navigation while maintenance is active.
"""
import json
import os

from django.conf import settings
from django.template.loader import render_to_string
from django.http import HttpResponse

STATE_FILE = os.environ.get(
    "MAINTENANCE_STATE_FILE",
    os.path.join(settings.BASE_DIR, "maintenance_state.json"),
)


def _read_file_state():
    """Read maintenance state from the shared JSON file (for external services)."""
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def get_maintenance_state():
    """Return the current maintenance state dict, or ``None`` if not active/expired."""
    # 1. Try the model (same process / shared DB)
    try:
        from apps.monitor.models import MaintenanceMode
        state = MaintenanceMode.state()
        if state and state.get("is_active"):
            return state
    except Exception:
        pass

    # 2. Fall back to the shared file (for separate services on the same host)
    file_state = _read_file_state()
    if file_state and file_state.get("is_active"):
        return file_state

    return None


class MaintenanceModeMiddleware:
    """Render a non-dismissable maintenance splash for all non-admin requests
    when maintenance mode is active."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Always allow these paths (admin, static, monitoring control):
        # — admin / static / maintenance API: infrastructure access
        # — login / logout / db-maintenance: so admins can toggle maintenance
        # — /api/*, /topology/, /slow-connection/, etc.: monitoring dashboard
        #   stays accessible while only the POS Apotek app (port 8000) shows
        #   the splash to end users.
        EXEMPT_PREFIX = ["/admin/", "/static/", "/api/maintenance",
                         "/login/", "/logout/", "/db-maintenance/",
                         "/api/", "/topology/", "/slow-connection/",
                         "/alerts/", "/deliveries/", "/config/",
                         "/endpoints/", "/logs/", "/webhooks/", "/users/",
                         "/dashboard"]
        EXEMPT_EXACT = ["/"]
        if request.path in EXEMPT_EXACT or any(request.path.startswith(p) for p in EXEMPT_PREFIX):
            return self.get_response(request)

        state = get_maintenance_state()
        if state:
            html = render_to_string("maintenance/splash.html", {
                "maintenance": state,
            })
            return HttpResponse(html, status=503)

        return self.get_response(request)
