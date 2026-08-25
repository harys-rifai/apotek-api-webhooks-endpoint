import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Avg, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings

from .models import APIEndpoint, APIRequestLog, WebhookEvent
from .services import call_api


# ── Helpers ──────────────────────────────────────────────────────────────────

def _stats_for_period(days: int = 7) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = APIRequestLog.objects.filter(created_at__gte=since)
    total = qs.count()
    success = qs.filter(status=APIRequestLog.STATUS_SUCCESS).count()
    fail = qs.filter(status=APIRequestLog.STATUS_FAIL).count()
    error = qs.filter(status=APIRequestLog.STATUS_ERROR).count()
    avg_ms = qs.aggregate(a=Avg("response_time_ms"))["a"] or 0
    rate = round((success / total * 100), 1) if total else 0
    return {
        "total": total,
        "success": success,
        "fail": fail,
        "error": error,
        "avg_ms": round(avg_ms, 1),
        "success_rate": rate,
        "period_days": days,
    }


# ── Pages ─────────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    stats = _stats_for_period(7)
    recent_logs = APIRequestLog.objects.select_related("endpoint").order_by("-created_at")[:20]
    endpoints = APIEndpoint.objects.filter(is_active=True)
    webhook_count = WebhookEvent.objects.count()

    # Top slowest endpoints (last 7 days)
    slow = (
        APIRequestLog.objects.filter(created_at__gte=timezone.now() - timedelta(days=7))
        .values("path", "method")
        .annotate(avg_ms=Avg("response_time_ms"), calls=Count("id"))
        .order_by("-avg_ms")[:5]
    )

    context = {
        "stats": stats,
        "recent_logs": recent_logs,
        "endpoints": endpoints,
        "webhook_count": webhook_count,
        "slow_endpoints": list(slow),
        "active_menu": "dashboard",
    }
    return render(request, "monitor/dashboard.html", context)


@login_required
def endpoint_list(request):
    endpoints = APIEndpoint.objects.annotate(
        total=Count("logs"),
        success=Count("logs", filter=Q(logs__status="success")),
        fail=Count("logs", filter=Q(logs__status="fail")),
    ).order_by("module", "name")

    context = {"endpoints": endpoints, "active_menu": "endpoints"}
    return render(request, "monitor/endpoints.html", context)


@login_required
def endpoint_detail(request, pk):
    ep = get_object_or_404(APIEndpoint, pk=pk)
    logs = APIRequestLog.objects.filter(endpoint=ep).order_by("-created_at")[:100]
    stats = _stats_for_period_for_endpoint(ep, days=7)
    context = {
        "endpoint": ep,
        "logs": logs,
        "stats": stats,
        "active_menu": "endpoints",
    }
    return render(request, "monitor/endpoint_detail.html", context)


def _stats_for_period_for_endpoint(ep, days=7):
    since = timezone.now() - timedelta(days=days)
    qs = APIRequestLog.objects.filter(endpoint=ep, created_at__gte=since)
    total = qs.count()
    success = qs.filter(status="success").count()
    fail = qs.filter(status="fail").count()
    error = qs.filter(status="error").count()
    avg_ms = qs.aggregate(a=Avg("response_time_ms"))["a"] or 0
    rate = round((success / total * 100), 1) if total else 0
    return {
        "total": total, "success": success, "fail": fail,
        "error": error, "avg_ms": round(avg_ms, 1), "success_rate": rate,
    }


@login_required
def log_list(request):
    status_filter = request.GET.get("status", "")
    method_filter = request.GET.get("method", "")
    q_filter      = request.GET.get("q", "").strip()
    logs = APIRequestLog.objects.select_related("endpoint").order_by("-created_at")
    if status_filter:
        logs = logs.filter(status=status_filter)
    if method_filter:
        logs = logs.filter(method=method_filter)
    if q_filter:
        logs = logs.filter(path__icontains=q_filter)
    logs = logs[:500]
    context = {
        "logs": logs,
        "status_filter": status_filter,
        "method_filter": method_filter,
        "active_menu": "logs",
    }
    return render(request, "monitor/logs.html", context)


@login_required
def webhook_list(request):
    status_filter = request.GET.get("status", "")
    qs = WebhookEvent.objects.all()
    if status_filter in {"received", "processed", "failed"}:
        qs = qs.filter(status=status_filter)
    events = qs.order_by("-received_at")[:100]
    context = {
        "events": events,
        "active_menu": "webhooks",
        "status_filter": status_filter,
    }
    return render(request, "monitor/webhooks.html", context)


@login_required
def architecture_view(request):
    context = {"active_menu": "architecture"}
    return render(request, "monitor/architecture.html", context)


@login_required
def delivery_list(request):
    """Pantau pengantaran obat dari ApotekApps (/deliveries/)."""
    deliveries = []
    api_state = "ok"
    api_msg = ""
    api_unavailable = False
    endpoint = APIEndpoint.objects.filter(path="/deliveries/").first()
    try:
        res = call_api("GET", "/deliveries/", endpoint_obj=endpoint, save_log=True,
                       triggered_by="manual")
        if res.get("status") == APIRequestLog.STATUS_SUCCESS:
            data = res.get("data") or {}
            deliveries = data.get("results") or data.get("data") or []
            if isinstance(deliveries, dict):
                deliveries = [deliveries]
        else:
            status_code = res.get("status_code")
            raw = (res.get("error") or "").strip()
            # 404 / respons bukan JSON (halaman HTML) → endpoint belum tersedia
            if status_code == 404 or raw.lower().startswith("<!doctype") or "<html" in raw.lower():
                api_unavailable = True
                api_msg = "Endpoint /deliveries/ belum tersedia di ApotekApps."
            else:
                api_state = "error"
                api_msg = res.get("error") or f"HTTP {status_code}"
    except Exception as e:
        api_state = "error"
        api_msg = str(e)

    context = {
        "active_menu": "deliveries",
        "deliveries": deliveries,
        "api_state": api_state,
        "api_msg": api_msg,
        "api_unavailable": api_unavailable,
    }
    return render(request, "monitor/deliveries.html", context)


@login_required
def topology_view(request):
    context = {"active_menu": "topology"}
    return render(request, "monitor/topology.html", context)


# ── API Actions (AJAX) ────────────────────────────────────────────────────────

@login_required
def api_ping(request, pk):
    """Kirim satu request ke endpoint dan simpan log, return JSON."""
    ep = get_object_or_404(APIEndpoint, pk=pk)
    result = call_api(
        ep.method,
        ep.path,
        triggered_by="manual",
        endpoint_obj=ep,
    )
    return JsonResponse(result)


@login_required
def api_stats_json(request):
    """Kembalikan stats aggregate untuk chart (last N days)."""
    days = int(request.GET.get("days", 7))
    since = timezone.now() - timedelta(days=days)

    # Per-day breakdown
    from django.db.models.functions import TruncDate
    daily = (
        APIRequestLog.objects.filter(created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            total=Count("id"),
            success=Count("id", filter=Q(status="success")),
            fail=Count("id", filter=Q(status="fail")),
            error=Count("id", filter=Q(status="error")),
            avg_ms=Avg("response_time_ms"),
        )
        .order_by("day")
    )

    # Per-endpoint breakdown
    per_ep = (
        APIRequestLog.objects.filter(created_at__gte=since)
        .values("path", "method")
        .annotate(
            total=Count("id"),
            success=Count("id", filter=Q(status="success")),
            fail=Count("id", filter=Q(status="fail")),
            avg_ms=Avg("response_time_ms"),
        )
        .order_by("-total")[:10]
    )

    summary = _stats_for_period(days)

    return JsonResponse({
        "summary": summary,
        "daily": [
            {
                "day": str(d["day"]),
                "total": d["total"],
                "success": d["success"],
                "fail": d["fail"],
                "error": d["error"],
                "avg_ms": round(d["avg_ms"] or 0, 1),
            }
            for d in daily
        ],
        "per_endpoint": [
            {
                "path": e["path"],
                "method": e["method"],
                "total": e["total"],
                "success": e["success"],
                "fail": e["fail"],
                "avg_ms": round(e["avg_ms"] or 0, 1),
                "success_rate": round(e["success"] / e["total"] * 100, 1) if e["total"] else 0,
            }
            for e in per_ep
        ],
    })


@login_required
def api_activity_json(request):
    """Return recent activity so the architecture diagram can animate in realtime."""
    last_log = APIRequestLog.objects.order_by("-created_at").first()
    last_wh = WebhookEvent.objects.order_by("-received_at").first()
    since = timezone.now() - timedelta(seconds=10)
    recent_logs = APIRequestLog.objects.filter(created_at__gte=since).count()
    recent_wh = WebhookEvent.objects.filter(received_at__gte=since).count()
    return JsonResponse({
        "last_log_at": last_log.created_at.isoformat() if last_log else None,
        "last_log_status": last_log.status if last_log else None,
        "last_log_path": last_log.path if last_log else None,
        "last_wh_at": last_wh.received_at.isoformat() if last_wh else None,
        "last_wh_event": last_wh.event_type if last_wh else None,
        "recent_logs_10s": recent_logs,
        "recent_wh_10s": recent_wh,
        "total_logs": APIRequestLog.objects.count(),
        "total_wh": WebhookEvent.objects.count(),
        "server_time": timezone.now().isoformat(),
    })


def _apotek_apps_dir():
    """Best-effort path to the sibling ApotekApps project."""
    import os
    return os.path.join(os.path.dirname(str(settings.BASE_DIR)), "ApotekApps")


def _apotek_apps_config():
    """Read ApotekApps/.env (best-effort). Returns a getter with defaults."""
    import os
    apps_env = os.path.join(_apotek_apps_dir(), ".env")
    try:
        from decouple import Config, RepositoryEnv
        cfg = Config(RepositoryEnv(apps_env))
        return lambda key, default=None: cfg.get(key, default=default)
    except Exception:
        return lambda key, default=None: default


def _probe_apotek_db():
    """Return ('healthy'|'critical', detail) by probing ApotekApps PostgreSQL.

    Tries a real psycopg connection first; falls back to a TCP socket check
    on host:port so we still detect a disconnect without the driver.
    """
    cfg = _apotek_apps_config()
    host = cfg("DB_HOST", "localhost")
    port = int(cfg("DB_PORT", 5432))
    name = cfg("DB_NAME", "apotek_pos")
    user = cfg("DB_USER", "postgres")
    password = cfg("DB_PASSWORD", "")

    # 1) TCP reachability
    import socket
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except Exception as e:
        return "critical", f"DB unreachable: {e}"

    # 2) real connection if driver available
    try:
        import psycopg
        conn = psycopg.connect(
            host=host, port=port, dbname=name, user=user,
            password=password, connect_timeout=2,
        )
        conn.close()
        return "healthy", "connected"
    except ImportError:
        return "healthy", "port open (no driver)"
    except Exception as e:
        return "critical", f"connect failed: {e}"


def _parse_redis_url(url: str) -> dict:
    """Parse redis://[:password@]host:port/db into parts (no external deps)."""
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url)
    db = 0
    if parsed.path and len(parsed.path) > 1:
        try:
            db = int(parsed.path.lstrip("/"))
        except ValueError:
            db = 0
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 6379,
        "password": unquote(parsed.password) if parsed.password else "",
        "db": db,
        "ssl": parsed.scheme == "rediss",
    }


def _probe_redis():
    """Probe Redis with a raw RESP PING (no redis-py dependency required).

    Returns (status, detail, meta) where status is healthy|warning|critical.
    """
    import socket
    import time

    cfg = _apotek_apps_config()
    url = cfg("REDIS_URL", "redis://127.0.0.1:6379/1")
    info = _parse_redis_url(url)
    meta = {"host": f"{info['host']}:{info['port']}", "db": info["db"]}

    def encode(*args):
        out = f"*{len(args)}\r\n".encode()
        for a in args:
            a = str(a).encode()
            out += b"$%d\r\n%s\r\n" % (len(a), a)
        return out

    try:
        started = time.time()
        with socket.create_connection((info["host"], info["port"]), timeout=2) as sock:
            if info["ssl"]:
                import ssl as _ssl
                sock = _ssl.create_default_context().wrap_socket(
                    sock, server_hostname=info["host"]
                )
            sock.settimeout(2)
            payload = b""
            if info["password"]:
                payload += encode("AUTH", info["password"])
            payload += encode("PING")
            payload += encode("INFO", "server")
            sock.sendall(payload)

            raw = b""
            deadline = time.time() + 2
            while b"+PONG" not in raw and b"-" not in raw[:1] and time.time() < deadline:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                raw += chunk
                if b"redis_version" in raw or b"-ERR" in raw or b"-NOAUTH" in raw:
                    break

        latency = round((time.time() - started) * 1000, 1)
        meta["latency_ms"] = latency
        text = raw.decode(errors="replace")

        if "NOAUTH" in text or "WRONGPASS" in text or "invalid password" in text.lower():
            return "critical", "auth failed", meta
        if "+PONG" not in text:
            return "critical", "no PONG response", meta

        for line in text.splitlines():
            if line.startswith("redis_version:"):
                meta["version"] = line.split(":", 1)[1].strip()
                break
        return "healthy", f"PONG {latency} ms", meta
    except Exception as e:
        return "critical", f"unreachable: {e}", meta


def _probe_media():
    """Probe ApotekApps media storage directory (exists + writable + size)."""
    import os

    cfg = _apotek_apps_config()
    media_root = cfg("MEDIA_ROOT") or os.path.join(_apotek_apps_dir(), "media")
    meta = {"path": media_root}

    if not os.path.isdir(media_root):
        return "critical", "directory missing", meta
    if not os.access(media_root, os.W_OK):
        return "warning", "not writable", meta

    files = 0
    total = 0
    try:
        for root, _dirs, names in os.walk(media_root):
            for fn in names:
                if fn.startswith("."):
                    continue
                files += 1
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
                if files >= 20000:  # safety cap
                    break
            if files >= 20000:
                break
    except OSError as e:
        return "warning", f"scan error: {e}", meta

    if total >= 1024 ** 3:
        size = f"{total / 1024 ** 3:.1f} GB"
    elif total >= 1024 ** 2:
        size = f"{total / 1024 ** 2:.1f} MB"
    elif total >= 1024:
        size = f"{total / 1024:.1f} KB"
    else:
        size = f"{total} B"

    meta.update({"files": files, "size": size, "bytes": total})
    return "healthy", f"{files} files · {size}", meta


@login_required
def api_topology_json(request):
    """Dynatrace-style smartscape: services as nodes, traffic as edges, live health."""
    now = timezone.now()
    since = now - timedelta(minutes=5)

    # Real health probes for ApotekApps backing services
    db_status, db_detail = _probe_apotek_db()
    redis_status, redis_detail, redis_meta = _probe_redis()
    media_status, media_detail, media_meta = _probe_media()

    # Build nodes from monitored endpoints (grouped by module = service)
    eps = APIEndpoint.objects.filter(is_active=True)
    modules = {}
    for ep in eps:
        modules.setdefault(ep.module, []).append(ep)

    nodes = []
    edges = []

    # Core infrastructure nodes
    nodes.append({
        "id": "pg", "label": "PostgreSQL", "kind": "database",
        "tech": "PostgreSQL 16", "status": db_status, "detail": db_detail,
    })
    if redis_meta.get("version"):
        redis_tech = f"Redis {redis_meta['version']} · db{redis_meta.get('db', 0)}"
    else:
        redis_tech = f"Redis · {redis_meta.get('host', 'n/a')}"
    nodes.append({
        "id": "redis", "label": "Redis Cache", "kind": "cache",
        "tech": redis_tech,
        "status": redis_status, "detail": redis_detail,
        "host": redis_meta.get("host"), "db_index": redis_meta.get("db"),
        "latency_ms": redis_meta.get("latency_ms"),
    })
    nodes.append({
        "id": "media", "label": "Media Storage", "kind": "storage",
        "tech": f"Filesystem · {media_meta.get('size', '0 B')}",
        "status": media_status, "detail": media_detail,
        "path": media_meta.get("path"), "files": media_meta.get("files"),
    })
    # apps_api health depends on DB + recent ping success
    recent_all = APIRequestLog.objects.filter(created_at__gte=since)
    recent_total = recent_all.count()
    recent_fail = recent_all.filter(status__in=["fail", "error"]).count()
    if db_status == "critical":
        apps_status = "critical"
    elif recent_total and (recent_fail / recent_total) > 0.5:
        apps_status = "critical"
    elif recent_total and (recent_fail / recent_total) > 0.2:
        apps_status = "warning"
    elif redis_status == "critical" or media_status == "critical":
        # Redis has a locmem fallback and media only affects uploads → degraded, not down
        apps_status = "warning"
    else:
        apps_status = "healthy"
    nodes.append({
        "id": "apps_api", "label": "ApotekApps REST API", "kind": "service",
        "tech": "Django + DRF :8000", "status": apps_status,
        "detail": f"DB: {db_status} · Redis: {redis_status} · Media: {media_status}",
    })
    nodes.append({
        "id": "monitor", "label": "ApotekMonitor", "kind": "service",
        "tech": "Django :8090", "status": "healthy",
    })
    nodes.append({
        "id": "monitor_db", "label": "Monitor SQLite", "kind": "database",
        "tech": "SQLite", "status": "healthy",
    })

    # Module → service nodes (one per module = microservice)
    for mod, ep_list in modules.items():
        q = APIRequestLog.objects.filter(endpoint__in=ep_list, created_at__gte=since)
        total = q.count()
        succ = q.filter(status="success").count()
        avg = q.aggregate(a=Avg("response_time_ms"))["a"] or 0
        rate = round(succ / total * 100, 1) if total else 100
        status = "healthy" if rate >= 95 else ("warning" if rate >= 80 else "critical")
        if total == 0:
            status = "idle"
        nodes.append({
            "id": f"svc_{mod}", "label": mod.capitalize(), "kind": "service",
            "tech": f"{len(ep_list)} endpoints",
            "status": status, "requests_5m": total,
            "success_rate": rate, "avg_ms": round(avg, 1),
        })
        # edge: ApotekApps API -> module service
        edges.append({"from": "apps_api", "to": f"svc_{mod}",
                      "requests_5m": total, "status": status})

    # edges: infra relationships (reflect real health)
    edges.append({"from": "pg", "to": "apps_api", "requests_5m": 0, "status": db_status,
                  "label": "SQL"})
    edges.append({"from": "redis", "to": "apps_api", "requests_5m": 0, "status": redis_status,
                  "label": "cache"})
    edges.append({"from": "media", "to": "apps_api", "requests_5m": 0, "status": media_status,
                  "label": "files"})
    edges.append({"from": "apps_api", "to": "monitor", "requests_5m": 0, "status": apps_status})
    edges.append({"from": "monitor", "to": "monitor_db", "requests_5m": 0, "status": "healthy"})

    # overall health
    total_all = APIRequestLog.objects.filter(created_at__gte=since).count()
    succ_all = APIRequestLog.objects.filter(created_at__gte=since, status="success").count()
    overall = round(succ_all / total_all * 100, 1) if total_all else 100

    return JsonResponse({
        "nodes": nodes,
        "edges": edges,
        "overall_success_rate": overall,
        "total_requests_5m": total_all,
        "infra": {
            "postgres": {"status": db_status, "detail": db_detail},
            "redis": {"status": redis_status, "detail": redis_detail, **redis_meta},
            "media": {"status": media_status, "detail": media_detail, **media_meta},
        },
        "server_time": now.isoformat(),
    })


# ── Webhook receiver ──────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def webhook_receiver(request):
    """Terima event dari ApotekApps (atau sistem lain)."""
    try:
        payload = json.loads(request.body or "{}")
        event_type = payload.get("event", "unknown")
        source_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR"))
        WebhookEvent.objects.create(
            event_type=event_type,
            source_ip=source_ip,
            payload=json.dumps(payload)[:5000],
            status=WebhookEvent.STATUS_RECEIVED,
        )
        return JsonResponse({"received": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)
