import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Avg, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

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
    events = WebhookEvent.objects.order_by("-received_at")[:100]
    context = {"events": events, "active_menu": "webhooks"}
    return render(request, "monitor/webhooks.html", context)


@login_required
def architecture_view(request):
    context = {"active_menu": "architecture"}
    return render(request, "monitor/architecture.html", context)


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


@login_required
def api_topology_json(request):
    """Dynatrace-style smartscape: services as nodes, traffic as edges, live health."""
    now = timezone.now()
    since = now - timedelta(minutes=5)

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
        "tech": "PostgreSQL 16", "status": "healthy",
    })
    nodes.append({
        "id": "apps_api", "label": "ApotekApps REST API", "kind": "service",
        "tech": "Django + DRF :8000", "status": "healthy",
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

    # edges: infra relationships
    edges.append({"from": "pg", "to": "apps_api", "requests_5m": 0, "status": "healthy"})
    edges.append({"from": "apps_api", "to": "monitor", "requests_5m": 0, "status": "healthy"})
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
