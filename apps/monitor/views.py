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
    logs = APIRequestLog.objects.select_related("endpoint").order_by("-created_at")
    if status_filter:
        logs = logs.filter(status=status_filter)
    if method_filter:
        logs = logs.filter(method=method_filter)
    logs = logs[:200]
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
