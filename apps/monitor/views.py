import json
from datetime import timedelta

import urllib.error as urllib_error
import urllib.request as urllib_request

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Avg, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings

from .models import (APIEndpoint, APIRequestLog, WebhookEvent, Alert,
                      AiInsight, NodeLayout, AIConfig, AIChatLog,
                      ConnectionConfig)
from .services import call_api
from .ai_insight import generate_ai_insight
from .ai_chat import call_ai_chat


# ── Helpers ──────────────────────────────────────────────────────────────────

def _human_size(num: float) -> str:
    """Format a byte count into a human-readable string (KB/MB/GB/…)."""
    try:
        n = float(num)
    except (TypeError, ValueError):
        return "n/a"
    if n < 0:
        return "n/a"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.1f} {units[i]}"


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
    # "fail" excludes client errors (4xx) from empty/synthetic probes — those
    # mean the endpoint is reachable and responded, not an outage. Only 5xx /
    # timeout / connection errors count as real failures.
    endpoints = APIEndpoint.objects.annotate(
        total=Count("logs"),
        success=Count("logs", filter=Q(logs__status="success")),
        fail=Count("logs", filter=Q(
            Q(logs__status="fail") | Q(logs__status="error")
        )),
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
    # "reachable" = endpoint merespons (termasuk 4xx). Berguna untuk availabilitas,
    # tapi tidak dipakai sebagai Success Rate agar angka jujur.
    reachable = success + qs.filter(
        status="fail", status_code__gte=400, status_code__lt=500
    ).count()
    rate = round((success / total * 100), 1) if total else 0
    avail = round((reachable / total * 100), 1) if total else 0
    return {
        "total": total, "success": success, "fail": fail,
        "error": error, "avg_ms": round(avg_ms, 1),
        "success_rate": rate, "availability": avail,
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


@login_required
def alerts_view(request):
    level = request.GET.get("level", "")
    qs = Alert.objects.all()
    if level in {Alert.LEVEL_INFO, Alert.LEVEL_WARNING, Alert.LEVEL_CRITICAL, Alert.LEVEL_SUCCESS}:
        qs = qs.filter(level=level)
    alerts = qs[:200]
    context = {
        "active_menu": "alerts",
        "alerts": alerts,
        "level_filter": level,
        "unread": Alert.objects.filter(is_read=False).count(),
    }
    return render(request, "monitor/alerts.html", context)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def config_view(request):
    """Halaman Config: atur koneksi SQLite, PostgreSQL, Redis, dan AI."""
    cc = ConnectionConfig.get_active()
    context = {
        "active_menu": "config",
        "cfg": cc,
        "ai_cfg": AIConfig.get_active(),
        "sqlite_path": str(settings.DATABASES.get("default", {}).get("NAME")),
        "apotek_email": _apotekapps_email_config(),
    }
    return render(request, "monitor/config.html", context)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def api_config_apotek_email(request):
    """Mirror konfigurasi email dari ApotekApps (/api/common/system-status/).

    Read-only: ApotekApps adalah pemilik konfigurasi SMTP-nya.
    """
    cfg = _apotekapps_email_config()
    if not cfg:
        return JsonResponse({
            "ok": False, "configured": False,
            "detail": "SMTP belum dikonfigurasi di ApotekApps.",
        })
    return JsonResponse({"ok": True, "configured": True, "email": cfg})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
@require_POST
def api_config_save(request):
    """Simpan pengaturan koneksi dari halaman Config."""
    import os
    cc = ConnectionConfig.get_active()
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        return JsonResponse({"error": "Payload JSON tidak valid."}, status=400)

    section = data.get("section")
    if section == "sqlite":
        cc.sqlite_path = (data.get("sqlite_path") or "").strip()
    elif section == "postgres":
        cc.pg_host = (data.get("pg_host") or "").strip()
        if data.get("pg_port"):
            try:
                cc.pg_port = int(data["pg_port"])
            except (TypeError, ValueError):
                return JsonResponse({"error": "Port PostgreSQL harus angka."}, status=400)
        else:
            cc.pg_port = None
        cc.pg_name = (data.get("pg_name") or "").strip()
        cc.pg_user = (data.get("pg_user") or "").strip()
        if data.get("pg_password"):
            cc.pg_password = data["pg_password"]
    elif section == "redis":
        cc.redis_url = (data.get("redis_url") or "").strip()
    elif section == "ai":
        cc.ai_enabled = bool(data.get("ai_enabled", False))
        cc.ai_base_url = (data.get("ai_base_url") or "").strip()
        cc.ai_model = (data.get("ai_model") or "").strip()
        if data.get("ai_api_key"):
            cc.ai_api_key = data["ai_api_key"]
    else:
        return JsonResponse({"error": "Section tidak dikenal."}, status=400)

    cc.save()

    # Sinkronkan bagian AI ke AIConfig agar chatbot ikut terupdate.
    if section == "ai":
        ai = AIConfig.get_active()
        ai.enabled = cc.ai_enabled
        ai.base_url = cc.ai_base_url
        ai.model = cc.ai_model
        if data.get("ai_api_key"):
            ai.api_key = cc.ai_api_key
        ai.save()

    return JsonResponse({
        "ok": True,
        "config": {
            "sqlite_path": cc.sqlite_path,
            "pg_host": cc.pg_host, "pg_port": cc.pg_port,
            "pg_name": cc.pg_name, "pg_user": cc.pg_user,
            "pg_password_masked": cc.mask_pg_password(),
            "redis_url": cc.redis_url,
            "redis_password_masked": cc.mask_redis_password(),
            "ai_enabled": cc.ai_enabled, "ai_base_url": cc.ai_base_url,
            "ai_model": cc.ai_model, "ai_api_key_masked": cc.mask_ai_key(),
        },
    })


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def api_config_test(request):
    """Uji koneksi untuk satu section (sqlite/postgres/redis/ai)."""
    section = request.GET.get("section", "")
    cfg = _apotek_apps_config()
    result = {"section": section, "status": "unknown", "detail": ""}

    if section == "postgres":
        status, detail = _probe_apotek_db()
        result.update(status=status, detail=detail)
    elif section == "redis":
        status, detail, meta = _probe_redis()
        result.update(status=status, detail=detail, **meta)
    elif section == "sqlite":
        path = (ConnectionConfig.get_active().sqlite_path
                or str(settings.DATABASES.get("default", {}).get("NAME")))
        try:
            import os
            if os.path.exists(path):
                result.update(status="healthy", detail=f"file ada · {os.path.getsize(path)} bytes")
            else:
                result.update(status="critical", detail="file tidak ditemukan")
        except Exception as e:
            result.update(status="critical", detail=str(e))
    elif section == "ai":
        ai = _effective_ai_config()
        if not ai.enabled or not ai.api_key or not ai.base_url:
            result.update(status="warning", detail="AI belum diaktifkan/terisi lengkap")
        else:
            try:
                messages_ = [{"role": "user", "content": "ping"}]
                call_ai_chat(messages_, config=ai, temperature=0)
                result.update(status="healthy", detail="AI merespons")
            except Exception as e:
                result.update(status="critical", detail=f"gagal: {e}")
    else:
        return JsonResponse({"error": "Section tidak dikenal."}, status=400)

    return JsonResponse(result)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
@require_POST
def api_config_ai_autodiscover(request):
    """Cari model free otomatis dari router AI (9router) dan simpan ke config.

    Mengambil daftar model via /v1/models, memilih model free/ringan, lalu
    menyimpannya ke ConnectionConfig & AIConfig.
    """
    cc = ConnectionConfig.get_active()
    ai = AIConfig.get_active()
    base_url = cc.ai_base_url or ai.base_url
    api_key = cc.ai_api_key or ai.api_key
    if not base_url or not api_key:
        return JsonResponse(
            {"ok": False, "error": "Isi & simpan Base URL dan API Key AI dulu."},
            status=400,
        )

    try:
        models = fetch_router_models(base_url, api_key)
    except RuntimeError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=502)

    if not models:
        return JsonResponse(
            {"ok": False, "error": "Tidak ada model di router."}, status=404)

    # Susun kandidat free/ringan, lalu verifikasi dengan ping sungguhan agar
    # terpilih model yang BENAR-BENAR bisa dipakai (bukan cuma by name).
    candidates = rank_free_models(models)
    chosen = None
    tried = []
    base_cfg = type("C", (), {})()
    base_cfg.base_url = base_url
    base_cfg.api_key = api_key
    base_cfg.enabled = True
    for cand in candidates:
        base_cfg.model = cand
        tried.append(cand)
        try:
            call_ai_chat([{"role": "user", "content": "ping"}],
                         config=base_cfg, temperature=0)
            chosen = cand
            break
        except Exception:
            continue

    # fallback: bila semua kandidat gagal (mis. router limit), pakai pilihan by name
    if not chosen:
        chosen = pick_free_model(models)
        detail = (f"Model free by-name: {chosen}. "
                  f"Peringatan: {len(tried)} kandidat diuji tapi gagal merespons "
                  f"(bisa jadi limit/balance router).")
    else:
        detail = f"Model free berfungsi dipilih: {chosen}"

    # simpan ke kedua config agar konsisten
    cc.ai_model = chosen
    cc.save()
    ai.model = chosen
    ai.save()

    return JsonResponse({
        "ok": True,
        "model": chosen,
        "verified": chosen in tried,
        "total": len(models),
        "tried": tried[:12],
        "models": models,
        "detail": detail,
    })


# ── API Actions (AJAX) ────────────────────────────────────────────────────────

@login_required
def api_endpoint_stats(request, pk):
    """Return recalculated stats for one endpoint (after a manual ping)."""
    ep = get_object_or_404(APIEndpoint, pk=pk)
    return JsonResponse({"id": ep.pk, **_stats_for_period_for_endpoint(ep, days=7)})


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
    """Return recent activity so the topology smartscape can animate in realtime."""
    last_log = APIRequestLog.objects.order_by("-created_at").first()
    last_wh = WebhookEvent.objects.order_by("-received_at").first()
    since = timezone.now() - timedelta(seconds=10)
    recent_logs = APIRequestLog.objects.filter(created_at__gte=since).count()
    recent_wh = WebhookEvent.objects.filter(received_at__gte=since).count()

    # real infra health (same probes used by the topology smartscape)
    pg_status, pg_detail = _probe_apotek_db()
    redis_status, redis_detail, redis_meta = _probe_redis()
    media_status, media_detail, media_meta = _probe_media()

    # real throughput for the ApotekApps -> Monitor flow (last 5 min)
    m5 = timezone.now() - timedelta(minutes=5)
    flow_q = APIRequestLog.objects.filter(created_at__gte=m5)
    flow_total = flow_q.count()
    flow_succ = flow_q.filter(status="success").count()
    flow_avg = flow_q.aggregate(a=Avg("response_time_ms"))["a"] or 0
    flow_rate = round(flow_succ / flow_total * 100, 1) if flow_total else 100

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
        "infra": {
            "postgres": {"status": pg_status, "detail": pg_detail},
            "redis": {"status": redis_status, "detail": redis_detail, **redis_meta},
            "media": {"status": media_status, "detail": media_detail, **media_meta},
        },
        "flow": {
            "requests_5m": flow_total,
            "success_rate": flow_rate,
            "avg_ms": round(flow_avg, 1),
            "per_sec": round(flow_total / 300, 2),
        },
        "server_time": timezone.now().isoformat(),
    })


@login_required
def api_db_sizes(request):
    """Return sizes for every datastore: monitor SQLite, ApotekApps PostgreSQL,
    and Redis. Used by the topology 'Storage & Database' panel."""
    sqlite_path = settings.DATABASES.get("default", {}).get("NAME")
    pg = _postgres_size()
    redis = _redis_size()

    sqlite_bytes = _sqlite_size(sqlite_path)
    try:
        from django.db import connection
        sqlite_tables = connection.introspection.table_names()
    except Exception:
        sqlite_tables = []

    data = {
        "sqlite": {
            "label": "SQLite (Monitor)",
            "path": str(sqlite_path),
            "bytes": sqlite_bytes,
            "human": _human_size(sqlite_bytes),
            "tables": len(sqlite_tables),
            "status": "healthy" if sqlite_bytes > 0 else "warning",
        },
        "postgres": {
            "label": "PostgreSQL (ApotekApps)",
            "bytes": pg.get("bytes"),
            "human": _human_size(pg["bytes"]) if pg.get("bytes") is not None else "n/a",
            "tables": pg.get("tables"),
            "members": pg.get("members"),
            "points": pg.get("points"),
            "status": pg.get("status", "unknown"),
            "detail": pg.get("detail", ""),
        },
        "redis": {
            "label": "Redis Cache",
            "bytes": redis.get("bytes"),
            "human": _human_size(redis["bytes"]) if redis.get("bytes") is not None else "n/a",
            "keys": redis.get("keys"),
            "status": redis.get("status", "unknown"),
            "detail": redis.get("detail", ""),
        },
        "server_time": timezone.now().isoformat(),
    }
    return JsonResponse(data)


@login_required
@require_POST
def api_db_vacuum(request):
    """Jalankan VACUUM FULL pada PostgreSQL ApotekApps untuk memperkecil ukuran
    file dan mengembalikan ruang yang tidak terpakai."""
    import socket

    cfg = _apotek_apps_config()
    host = cfg("DB_HOST", "localhost")
    port = int(cfg("DB_PORT", 5432))
    name = cfg("DB_NAME", "apotek_pos")
    user = cfg("DB_USER", "postgres")
    password = cfg("DB_PASSWORD", "")

    try:
        import psycopg
        _connect = lambda: psycopg.connect(
            host=host, port=port, dbname=name, user=user,
            password=password, connect_timeout=5, autocommit=True,
        )
    except ImportError:
        try:
            import psycopg2
            _connect = lambda: psycopg2.connect(
                host=host, port=port, dbname=name, user=user,
                password=password, connect_timeout=5,
            )
        except ImportError:
            return JsonResponse(
                {"ok": False, "error": "no postgres driver (psycopg/psycopg2)"}, status=500)

    try:
        # VACUUM FULL cannot run inside a transaction block
        conn = _connect()
        try:
            conn.autocommit = True
        except Exception:
            pass
        with conn.cursor() as cur:
            cur.execute("VACUUM FULL")
        conn.close()
        return JsonResponse({"ok": True, "detail": f"VACUUM FULL selesai · {name}@{host}:{port}"})
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"VACUUM FULL gagal: {e}"}, status=500)


@login_required
@require_POST
def api_db_sqlite_vacuum(request):
    """Jalankan VACUUM pada SQLite Monitor untuk mengembalikan ruang kosong."""
    from django.db import connection
    from django.core.management import call_command
    path = settings.DATABASES.get("default", {}).get("NAME")
    # snapshot dulu sebagai jaminan jika VACUUM bermasalah
    try:
        call_command("db_backup", rotate=24)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Backup otomatis gagal: {e}"}, status=500)
    try:
        with connection.cursor() as cur:
            cur.execute("VACUUM")
        before = _sqlite_size(path)
        return JsonResponse({"ok": True, "detail": f"SQLite VACUUM selesai · {_human_size(before)}"})
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"SQLite VACUUM gagal: {e}"}, status=500)


@login_required
@require_POST
def api_db_redis_flush(request):
    """Jalankan FLUSHDB pada Redis (db terpilih) untuk membersihkan cache."""
    import socket
    import time

    cfg = _apotek_apps_config()
    url = cfg("REDIS_URL", "redis://127.0.0.1:6379/1")
    info = _parse_redis_url(url)

    def encode(*args):
        out = f"*{len(args)}\r\n".encode()
        for a in args:
            a = str(a).encode()
            out += b"$%d\r\n%s\r\n" % (len(a), a)
        return out

    try:
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
            payload += encode("SELECT", str(info["db"]))
            payload += encode("FLUSHDB")
            sock.sendall(payload)
            raw = b""
            deadline = time.time() + 2
            while time.time() < deadline:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                raw += chunk
                if b"+OK" in raw or b"-" in raw:
                    break
        text = raw.decode(errors="replace")
        if "+OK" in text:
            return JsonResponse({"ok": True, "detail": f"Redis FLUSHDB selesai · db{info['db']}"})
        return JsonResponse({"ok": False, "error": "respon tidak OK: " + text[:80]}, status=500)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Redis FLUSHDB gagal: {e}"}, status=500)


def _apotek_apps_dir():
    """Best-effort path to the sibling ApotekApps project."""
    import os
    return os.path.join(os.path.dirname(str(settings.BASE_DIR)), "ApotekApps")


def _conn_cfg():
    """Singleton ConnectionConfig (pengaturan dari menu Config)."""
    try:
        return ConnectionConfig.get_active()
    except Exception:
        return None


def _effective_ai_config():
    """Gabungkan AIConfig dengan override dari ConnectionConfig.

    ConnectionConfig adalah sumber kebenaran utama (diisi dari menu Config);
    AIConfig disinkronkan saat menyimpan section AI, tapi bila ada nilai
    ConnectionConfig yang lebih baru, gunakan itu agar chatbot konsisten.
    """
    ai = AIConfig.get_active()
    cc = _conn_cfg()
    if not cc:
        return ai
    if cc.ai_base_url:
        ai.base_url = cc.ai_base_url
    if cc.ai_model:
        ai.model = cc.ai_model
    if cc.ai_api_key:
        ai.api_key = cc.ai_api_key
    if cc.ai_enabled:
        # hanya nyalakan bila user mengaktifkan di ConnectionConfig
        ai.enabled = True
    # bila ConnectionConfig pernah diisi, jangan biarkan AI mati bila
    # field enabled di ConnectionConfig false tapi ada url+key.
    if cc.ai_base_url and cc.ai_api_key and not ai.enabled:
        ai.enabled = cc.ai_enabled
    return ai


def fetch_router_models(base_url, api_key, timeout=60):
    """Ambil daftar model dari router AI OpenAI-compatible (GET /v1/models).

    Mengembalikan list id model (str). Raise RuntimeError bila gagal.
    Endpoint /v1/models di 9router sering lambat, jadi timeout longgar + retry.
    """
    if not base_url:
        raise RuntimeError("Base URL AI belum diisi.")
    url = base_url.rstrip("/") + "/v1/models"
    last_err = None
    for attempt in range(2):
        req = urllib_request.Request(url, headers={
            "Authorization": f"Bearer {api_key or ''}",
            "Content-Type": "application/json",
        })
        try:
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            objs = (data.get("data") or []) if isinstance(data, dict) else []
            return [m.get("id") for m in objs if m.get("id")]
        except urllib_error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:200]
            raise RuntimeError(f"Router menolak ({e.code}): {detail}")
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Gagal memuat daftar model: {last_err}")


def pick_free_model(model_ids):
    """Pilih model free/termurah dari daftar id model router.

    Prioritas:
      1. id mengandung 'free' (mis. my-free-tiers) — tier gratis eksplisit.
      2. model ringan: '-extra-low', '-nano', '-mini', '-low', '-lite', '-flash'.
      3. fallback: model pertama yang bukan agentic/reasoner/thinking.
    """
    ids = list(model_ids)
    if not ids:
        return None
    ranked = rank_free_models(ids)
    return ranked[0] if ranked else None


def rank_free_models(model_ids):
    """Kembalikan list id model terurut prioritas free/ringan.

    Urutan: (1) eksplisit 'free', (2) ringan (extra-low/nano/mini/low/lite/flash),
    (3) sisanya kecuali varian berat/agentic, (4) sisanya.
    """
    ids = list(model_ids)
    if not ids:
        return []

    # 1) eksplisit "free"
    free = [m for m in ids if "free" in m.lower()]
    # 2) ringan (urut prioritas kata kunci)
    light_kw = ["extra-low", "nano", "mini", "low", "lite", "-flash-", "flash-lite"]
    light = []
    for kw in light_kw:
        for m in ids:
            if kw in m.lower() and m not in light:
                light.append(m)
    # 3) hindari varian berat/agentic
    skip = ("agentic", "thinking", "reasoner", "opus", "pro", "ultra", "max")
    other = [m for m in ids if not any(s in m.lower() for s in skip)]
    other = [m for m in other if m not in free and m not in light]
    rest = [m for m in ids if m not in free and m not in light and m not in other]
    return free + light + other + rest


def _apotek_apps_config():
    """Read ApotekApps/.env (best-effort). Returns a getter with defaults.

    Menambahkan override dari ConnectionConfig bila diisi oleh user.
    """
    import os
    apps_env = os.path.join(_apotek_apps_dir(), ".env")
    try:
        from decouple import Config, RepositoryEnv
        cfg = Config(RepositoryEnv(apps_env))
        base = lambda key, default=None: cfg.get(key, default=default)
    except Exception:
        base = lambda key, default=None: default

    cc = _conn_cfg()
    overrides = {}
    if cc:
        if cc.pg_host:
            overrides["DB_HOST"] = cc.pg_host
        if cc.pg_port:
            overrides["DB_PORT"] = str(cc.pg_port)
        if cc.pg_name:
            overrides["DB_NAME"] = cc.pg_name
        if cc.pg_user:
            overrides["DB_USER"] = cc.pg_user
        if cc.pg_password:
            overrides["DB_PASSWORD"] = cc.pg_password
        if cc.redis_url:
            overrides["REDIS_URL"] = cc.redis_url

    def getter(key, default=None):
        if key in overrides:
            return overrides[key]
        return base(key, default)
    return getter


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


def _sqlite_size(path) -> int:
    """Return the byte size of a file (0 if missing)."""
    import os
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _postgres_size() -> dict:
    """Return {'bytes': int|None, 'tables': int|None, 'status': ...} for the
    ApotekApps PostgreSQL replica via a real psycopg connection when available."""
    cfg = _apotek_apps_config()
    host = cfg("DB_HOST", "localhost")
    port = int(cfg("DB_PORT", 5432))
    name = cfg("DB_NAME", "apotek_pos")
    user = cfg("DB_USER", "postgres")
    password = cfg("DB_PASSWORD", "")

    try:
        import psycopg
        _connect = lambda: psycopg.connect(
            host=host, port=port, dbname=name, user=user,
            password=password, connect_timeout=2,
        )
        _driver = "psycopg"
    except ImportError:
        try:
            import psycopg2
            _connect = lambda: psycopg2.connect(
                host=host, port=port, dbname=name, user=user,
                password=password, connect_timeout=2,
            )
            _driver = "psycopg2"
        except ImportError:
            return {"bytes": None, "tables": None, "status": "unknown",
                    "detail": "no postgres driver (psycopg/psycopg2)"}

    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_database_size(%s)", (name,)
            )
            size = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
                "AND table_type = 'BASE TABLE'"
            )
            tables = cur.fetchone()[0]
            # member & poin loyalty (tabel `members`, soft-delete is_deleted)
            members = points = None
            try:
                cur.execute(
                    "SELECT count(*), COALESCE(sum(points),0) "
                    "FROM members WHERE is_deleted = FALSE"
                )
                members, points = cur.fetchone()
            except Exception:
                members = points = None
        conn.close()
        return {"bytes": size, "tables": tables, "members": members,
                "points": points, "status": "healthy",
                "detail": f"{name}@{host}:{port}"}
    except Exception as e:
        return {"bytes": None, "tables": None, "members": None, "points": None,
                "status": "critical", "detail": f"connect failed: {e}"}


def _redis_size() -> dict:
    """Return {'bytes': int|None, 'keys': int|None, 'status': ...} for Redis
    via a raw RESP INFO+DBSIZE (no redis-py dependency required)."""
    import socket
    import time

    cfg = _apotek_apps_config()
    url = cfg("REDIS_URL", "redis://127.0.0.1:6379/1")
    info = _parse_redis_url(url)

    def encode(*args):
        out = f"*{len(args)}\r\n".encode()
        for a in args:
            a = str(a).encode()
            out += b"$%d\r\n%s\r\n" % (len(a), a)
        return out

    try:
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
            payload += encode("INFO", "memory")
            payload += encode("DBSIZE")
            sock.sendall(payload)

            raw = b""
            deadline = time.time() + 2
            while time.time() < deadline:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                raw += chunk
                if b"used_memory:" in raw and b":" in raw.split(b"used_memory:")[1][:40] and b"\r\n" in raw and b":" in raw.split(b"used_memory:")[1] and b"\r\n" in raw.split(b"used_memory:")[1]:
                    if b"\r\n:0\r\n" in raw or b"\r\n:1\r\n" in raw or (raw.count(b"\r\n:") >= 2):
                        break

        text = raw.decode(errors="replace")
        used = None
        for line in text.splitlines():
            if line.startswith("used_memory:"):
                try:
                    used = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
                break
        keys = None
        # DBSIZE response is the last integer reply "+:N\r\n"
        replies = [int(p[1:]) for p in text.replace("\r\n", "\n").split("\n") if p.startswith(":")]
        if replies:
            keys = replies[-1]
        status = "healthy" if used is not None else "warning"
        return {"bytes": used, "keys": keys, "status": status,
                "detail": f"{info['host']}:{info['port']} db{info['db']}"}
    except Exception as e:
        return {"bytes": None, "keys": None, "status": "critical",
                "detail": f"unreachable: {e}"}


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
            # server is reachable but rejects the configured password → config issue, not down
            return "warning", "auth failed (check REDIS_URL)", meta
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


def _probe_nginx():
    """Probe Nginx: process running + listening on :80/:443.

    Returns (status, detail, meta). status is healthy|warning|critical.
    """
    import shutil
    import subprocess

    meta = {}
    nginx_bin = shutil.which("nginx")
    meta["binary"] = nginx_bin or "not found"

    # 1) is nginx running?
    try:
        out = subprocess.run(
            ["pgrep", "-f", "nginx: master"],
            capture_output=True, text=True, timeout=2,
        )
        running = out.returncode == 0
    except Exception:
        running = False

    if not running:
        return "critical", "nginx not running", meta

    # 2) is it listening on 80/443?
    listening_80 = listening_443 = False
    try:
        import socket
        for port in (80, 443):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                    if port == 80: listening_80 = True
                    else: listening_443 = True
            except Exception:
                pass
        meta["port_80"] = listening_80
        meta["port_443"] = listening_443
    except Exception:
        pass

    if listening_80 or listening_443:
        ports = []
        if listening_80: ports.append("80")
        if listening_443: ports.append("443")
        return "healthy", f"running · :{'+'.join(ports)}", meta
    return "warning", "running but no listener on 80/443", meta


def _probe_python():
    """Probe the Python runtime that runs ApotekMonitor / ApotekApps.

    Returns (status, detail, meta). Healthy if a supported interpreter exists.
    """
    import subprocess
    import sys

    meta = {"version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"}
    meta["executable"] = sys.executable

    try:
        out = subprocess.run(
            [sys.executable, "--version"],
            capture_output=True, text=True, timeout=2,
        )
        ver = (out.stdout or out.stderr).strip().replace("Python ", "")
        if ver:
            meta["version"] = ver
    except Exception as e:
        return "critical", f"interpreter error: {e}", meta

    # ApotekApps may use a different python (e.g. 3.11 via homebrew)
    alt = None
    candidates = ["/opt/homebrew/bin/python3.11", "/usr/local/bin/python3.11", "python3.11"]
    for c in candidates:
        try:
            r = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                alt = (r.stdout or r.stderr).strip().replace("Python ", "")
                break
        except Exception:
            continue
    if alt:
        meta["apps_runtime"] = alt

    return "healthy", f"Python {meta['version']}", meta


def _human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _probe_system():
    """Host/OS-level health: disk, memory, and load average.

    Uses psutil when available; otherwise falls back to macOS/BSD CLI tools.
    Returns (status, detail, meta). Status is worst-of(disk, mem, load):
      healthy / warning / critical by usage thresholds.
    """
    import platform

    meta = {"platform": platform.system(), "hostname": platform.node()}
    disk_pct = mem_pct = load_pct = None

    # ── Disk (root / or MEDIA_ROOT if set) ──
    try:
        import shutil
        cfg = _apotek_apps_config()
        path = cfg("MEDIA_ROOT") or "/"
        du = shutil.disk_usage(path)
        disk_pct = round(du.used / du.total * 100, 1)
        meta["disk"] = {
            "path": path,
            "total": _human_bytes(du.total),
            "used": _human_bytes(du.used),
            "free": _human_bytes(du.free),
            "pct": disk_pct,
        }
    except Exception as e:
        meta["disk_error"] = str(e)

    # ── Memory ──
    try:
        import psutil
        mv = psutil.virtual_memory()
        mem_pct = round(mv.percent, 1)
        meta["mem"] = {
            "total": _human_bytes(mv.total),
            "used": _human_bytes(mv.used),
            "free": _human_bytes(mv.available),
            "pct": mem_pct,
        }
    except ImportError:
        # macOS fallback via vm_stat
        try:
            import subprocess
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=2).stdout
            page = 4096
            vals = {}
            for line in out.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    v = v.strip().rstrip(".").replace(",", "")
                    try:
                        vals[k.strip()] = int(v) * page
                    except ValueError:
                        pass
            used = vals.get("Pages active") + vals.get("Pages wired down") + vals.get("Pages occupied by compressor", 0)
            free = vals.get("Pages free", 0) + vals.get("Pages inactive", 0)
            total = used + free
            if total:
                mem_pct = round(used / total * 100, 1)
                meta["mem"] = {"used": _human_bytes(used), "free": _human_bytes(free), "pct": mem_pct}
        except Exception as e:
            meta["mem_error"] = str(e)
    except Exception as e:
        meta["mem_error"] = str(e)

    # ── Load average ──
    try:
        import os
        try:
            import psutil
            load1 = psutil.getloadavg()[0]
        except ImportError:
            load1 = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        load_pct = round(load1 / cpu_count * 100, 1)
        meta["load"] = {"load1": round(load1, 2), "cpus": cpu_count, "pct": load_pct}
    except Exception as e:
        meta["load_error"] = str(e)

    # ── Thresholds → status (warning >=80, critical >=90) ──
    def level(p):
        if p is None:
            return "healthy"
        if p >= 90:
            return "critical"
        if p >= 80:
            return "warning"
        return "healthy"

    worst = "healthy"
    for p in (disk_pct, mem_pct):
        lv = level(p)
        if lv == "critical":
            worst = "critical"
        elif lv == "warning" and worst != "critical":
            worst = "warning"
    # Load average is not pure CPU and macOS inflates it; use lenient bar:
    # warning >= 1.0/core (100%), critical >= 1.5/core (150%)
    if load_pct is not None:
        if load_pct >= 150:
            worst = "critical"
        elif load_pct >= 100 and worst != "critical":
            worst = "warning"

    parts = []
    if disk_pct is not None: parts.append(f"disk {disk_pct}%")
    if mem_pct is not None: parts.append(f"mem {mem_pct}%")
    if load_pct is not None: parts.append(f"load {load_pct}%")
    detail = " · ".join(parts) if parts else "metrics unavailable"
    return worst, detail, meta


def _apotekapps_email_config():
    """Baca konfigurasi email dari ApotekApps.

    Sumber utama: /api/common/system-config/ (lengkap: host, port, user,
    use_tls, use_ssl, from). Fallback: /api/common/system-status/ (hanya host).
    Kedua endpoint AllowAny — tidak butuh token. Mengembalikan dict
    {host, port, user, use_tls, use_ssl, from} atau {} bila gagal/tidak ada.
    """
    from django.conf import settings
    base = (getattr(settings, "APOTEK_API_BASE_URL", "http://127.0.0.1:8000/api")
            .rsplit("/api", 1)[0]).rstrip("/")

    def _get(path):
        try:
            with urllib_request.urlopen(base + path, timeout=4) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    # 1) system-config: konfigurasi lengkap
    data = _get("/api/common/system-config/")
    email = ((data or {}).get("config") or {}).get("email") if data else None
    if not email:
        # 2) fallback system-status: hanya host + status
        data = _get("/api/common/system-status/")
        email = ((data or {}).get("services") or {}).get("email")

    if not email:
        return {}
    host = (email.get("host") or "").strip()
    if not host or host == "—":
        return {}
    try:
        port = int(email.get("port") or 25)
    except (TypeError, ValueError):
        port = 25
    return {
        "host": host, "port": port,
        "user": email.get("user", ""),
        "use_tls": bool(email.get("use_tls", False)),
        "use_ssl": bool(email.get("use_ssl", False)),
        "from": email.get("from", ""),
    }


def _probe_email():
    """Probe the configured SMTP server for email delivery health.

    Konfigurasi SMTP dibaca dari ApotekApps (sumber kebenaran) lewat
    /api/common/system-status/. Bila tidak tersedia, fallback ke settings
    EMAIL_HOST lokal.
    """
    from django.conf import settings
    cfg = _apotekapps_email_config()
    host = cfg.get("host") or (getattr(settings, "EMAIL_HOST", "") or "")
    port = int(cfg.get("port") or getattr(settings, "EMAIL_PORT", 25) or 25)
    if not host:
        return "warning", "SMTP belum dikonfigurasi (EMAIL_HOST kosong).", {}
    import socket
    try:
        with socket.create_connection((host, port), timeout=3):
            return "healthy", f"SMTP terhubung · {host}:{port}", {"host": host, "port": port}
    except Exception as e:
        # Email is a non-critical notification channel — its outage does not
        # take down the API, so report it as warning, not critical.
        return "warning", f"SMTP unreachable: {e}", {"host": host, "port": port}


@login_required
def api_email_monitor(request):
    """Probe the SMTP server for the topology 'Email Monitoring' panel.

    GET /api/email/            → current SMTP health
    POST /api/email/?test=1    → kirim email uji (memakai send_mail Django)
    """
    status, detail, meta = _probe_email()
    if request.method == "POST" and request.GET.get("test"):
        from django.conf import settings
        host = getattr(settings, "EMAIL_HOST", "") or ""
        if not host:
            return JsonResponse({
                "ok": False, "tested": False,
                "status": status, "detail": detail, **meta,
                "error": "SMTP belum dikonfigurasi (EMAIL_HOST kosong).",
            }, status=400)
        recipient = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
        if not recipient:
            recipient = request.user.email or ""
        if not recipient:
            return JsonResponse({
                "ok": False, "tested": False,
                "status": status, "detail": detail, **meta,
                "error": "Tidak ada penerima email (EMAIL_HOST_USER / email user kosong).",
            }, status=400)
        try:
            from django.core.mail import send_mail
            send_mail(
                subject="[ApotekMonitor] Test Email Monitoring",
                message=("Ini adalah email uji dari panel Topologi · Email Monitoring.\n"
                         "Jika Anda menerima ini, server SMTP terkonfigurasi dengan benar."),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[recipient],
                fail_silently=False,
            )
            return JsonResponse({
                "ok": True, "tested": True, "status": status, "detail": detail,
                "message": f"Email uji dikirim ke {recipient}.", **meta,
            })
        except Exception as e:
            return JsonResponse({
                "ok": False, "tested": True,
                "status": "warning", "detail": detail,
                "error": f"Gagal mengirim email uji: {e}", **meta,
            }, status=400)

    return JsonResponse({
        "ok": True, "status": status, "detail": detail, **meta,
    })


@login_required
def api_topology_json(request):
    """Dynatrace-style smartscape: services as nodes, traffic as edges, live health."""
    now = timezone.now()
    since = now - timedelta(minutes=5)

    # Real health probes for ApotekApps backing services
    db_status, db_detail = _probe_apotek_db()
    pg = _postgres_size()
    redis_status, redis_detail, redis_meta = _probe_redis()
    media_status, media_detail, media_meta = _probe_media()
    nginx_status, nginx_detail, nginx_meta = _probe_nginx()
    python_status, python_detail, python_meta = _probe_python()
    system_status, system_detail, system_meta = _probe_system()
    email_status, email_detail, email_meta = _probe_email()

    # Build nodes from monitored endpoints (grouped by module = service)
    eps = APIEndpoint.objects.filter(is_active=True)
    modules = {}
    for ep in eps:
        modules.setdefault(ep.module, []).append(ep)

    nodes = []
    edges = []

    # Core infrastructure nodes
    pg_parts = [db_detail]
    if pg.get("members") is not None:
        pg_parts.append(f"Member: {pg['members']}")
    if pg.get("points") is not None:
        pg_parts.append(f"Poin: {pg['points']}")
    pg_detail_full = " · ".join(p for p in pg_parts if p)
    nodes.append({
        "id": "pg", "label": "PostgreSQL", "kind": "database",
        "tech": "PostgreSQL 16", "status": db_status, "detail": pg_detail_full,
        "members": pg.get("members"), "points": pg.get("points"),
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
        "id": "monitor", "label": "OrchestrationApps", "kind": "service",
        "tech": "Django :8090", "status": "healthy",
    })
    nodes.append({
        "id": "monitor_db", "label": "Monitor SQLite", "kind": "database",
        "tech": "SQLite", "status": "healthy",
    })
    nodes.append({
        "id": "email", "label": "Email Monitor", "kind": "service",
        "tech": f"SMTP · {email_meta.get('host', 'n/a')}:{email_meta.get('port', '')}",
        "status": email_status, "detail": email_detail,
    })
    # host-level runtime & web server
    nodes.append({
        "id": "python", "label": "Python Runtime", "kind": "runtime",
        "tech": python_meta.get("version", "Python"), "status": python_status,
        "detail": python_detail,
        "version": python_meta.get("version"),
        "apps_runtime": python_meta.get("apps_runtime"),
    })
    nodes.append({
        "id": "nginx", "label": "Nginx", "kind": "proxy",
        "tech": "Reverse Proxy", "status": nginx_status, "detail": nginx_detail,
        "port_80": nginx_meta.get("port_80"), "port_443": nginx_meta.get("port_443"),
    })
    nodes.append({
        "id": "system", "label": "System Host", "kind": "system",
        "tech": f"{system_meta.get('platform','')} · {system_meta.get('hostname','')}",
        "status": system_status, "detail": system_detail,
        "disk_pct": (system_meta.get("disk") or {}).get("pct"),
        "mem_pct": (system_meta.get("mem") or {}).get("pct"),
        "load_pct": (system_meta.get("load") or {}).get("pct"),
    })

    # Module → service nodes (one per module = microservice)
    for mod, ep_list in modules.items():
        q = APIRequestLog.objects.filter(endpoint__in=ep_list, created_at__gte=since)
        total = q.count()
        # Availability: 4xx (client_error) is "reachable", not a failure.
        # Only 5xx / timeout / connection errors count as outages.
        succ = q.filter(status="success").count()
        reachable = succ + q.filter(
            status="fail", status_code__gte=400, status_code__lt=500
        ).count()
        avg = q.aggregate(a=Avg("response_time_ms"))["a"] or 0
        rate = round(reachable / total * 100, 1) if total else 100
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
    edges.append({"from": "nginx", "to": "apps_api", "requests_5m": 0, "status": nginx_status,
                  "label": "proxy"})
    edges.append({"from": "python", "to": "apps_api", "requests_5m": 0, "status": python_status,
                  "label": "runtime"})
    edges.append({"from": "python", "to": "monitor", "requests_5m": 0, "status": python_status,
                  "label": "runtime"})
    edges.append({"from": "system", "to": "python", "requests_5m": 0, "status": system_status,
                  "label": "hosts"})
    edges.append({"from": "system", "to": "nginx", "requests_5m": 0, "status": system_status,
                  "label": "hosts"})
    edges.append({"from": "system", "to": "pg", "requests_5m": 0, "status": system_status,
                  "label": "hosts"})
    edges.append({"from": "apps_api", "to": "monitor", "requests_5m": 0, "status": apps_status})
    edges.append({"from": "monitor", "to": "monitor_db", "requests_5m": 0, "status": "healthy"})
    edges.append({"from": "monitor", "to": "email", "requests_5m": 0, "status": email_status,
                  "label": "notify"})
    edges.append({"from": "system", "to": "email", "requests_5m": 0, "status": system_status,
                  "label": "hosts"})

    # Member card — loyalty monitoring (member count + total poin from PostgreSQL)
    # Sama seperti node modul: "idle" bila tidak ada aktivitas terbaru, "warning"
    # hanya bila pembacaan data gagal.
    member_count = pg.get("members")
    member_points = pg.get("points")
    member_status = "idle" if member_count is not None else "warning"
    nodes.append({
        "id": "member", "label": "Member", "kind": "service",
        "tech": "Loyalty · Poin", "status": member_status,
        "members": member_count, "points": member_points,
        "detail": (f"Member: {member_count} · Poin: {member_points}"
                   if member_count is not None else "data tidak tersedia"),
    })
    edges.append({"from": "pg", "to": "member", "requests_5m": 0, "status": member_status,
                  "label": "members"})

    # overall health — 4xx is "reachable" (endpoint responded), not an outage.
    total_all = APIRequestLog.objects.filter(created_at__gte=since).count()
    succ_all = APIRequestLog.objects.filter(created_at__gte=since, status="success").count()
    reachable_all = succ_all + APIRequestLog.objects.filter(
        created_at__gte=since, status="fail",
        status_code__gte=400, status_code__lt=500,
    ).count()
    overall = round(reachable_all / total_all * 100, 1) if total_all else 100

    # overall STATUS combines API availability with CORE infra health only
    # (DB, Redis, Media, Nginx, Python, System). Non-fatal channels like Email
    # are excluded so a missing SMTP server cannot flip the whole system critical.
    core_infra = [db_status, redis_status, media_status, nginx_status,
                  python_status, system_status]
    if db_status == "critical":
        overall_status = "critical"
    elif "critical" in core_infra or overall < 80:
        overall_status = "critical"
    elif "warning" in core_infra or overall < 95:
        overall_status = "warning"
    else:
        overall_status = "healthy"

    return JsonResponse({
        "nodes": nodes,
        "edges": edges,
        "overall_success_rate": overall,
        "overall_status": overall_status,
        "total_requests_5m": total_all,
        "positions": {nl.node_id: {"x": nl.x, "y": nl.y} for nl in NodeLayout.objects.all()},
        "infra": {
            "postgres": {"status": db_status, "detail": db_detail},
            "redis": {"status": redis_status, "detail": redis_detail, **redis_meta},
            "media": {"status": media_status, "detail": media_detail, **media_meta},
            "nginx": {"status": nginx_status, "detail": nginx_detail, **nginx_meta},
            "python": {"status": python_status, "detail": python_detail, **python_meta},
            "system": {"status": system_status, "detail": system_detail, **system_meta},
            "email": {"status": email_status, "detail": email_detail, **email_meta},
        },
        "server_time": now.isoformat(),
    })


@login_required
@require_POST
def api_topology_layout(request):
    """Save manually-dragged node positions as the new default layout."""
    try:
        payload = json.loads(request.body or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)
    positions = payload.get("positions")
    if not isinstance(positions, dict):
        return JsonResponse({"ok": False, "error": "positions required"}, status=400)
    saved = 0
    for node_id, pos in positions.items():
        try:
            x = float(pos.get("x")); y = float(pos.get("y"))
        except (TypeError, ValueError):
            continue
        NodeLayout.objects.update_or_create(node_id=node_id, defaults={"x": x, "y": y})
        saved += 1
    return JsonResponse({"ok": True, "saved": saved})


@login_required
def api_backup_sync(request):
    """Trigger an on-demand sync of Monitor data (Alert/AiInsight/NodeLayout)
    from SQLite to the backup PostgreSQL. Intended to be polled periodically."""
    from io import StringIO
    from django.core.management import call_command
    out = StringIO()
    try:
        call_command("sync_to_postgres", stdout=out)
        return JsonResponse({"ok": True, "log": out.getvalue().strip()})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@login_required
def api_ai_insight(request):
    """Return the latest persisted AI insight.

    If ``?refresh=1`` is passed, a fresh insight is generated (and saved);
    otherwise a recent (<60s) cached row is reused to avoid spamming the DB on
    every poll.
    """
    force = request.GET.get("refresh") == "1"
    row = generate_ai_insight(force=force)
    return JsonResponse({
        "severity": row.severity,
        "summary": row.summary,
        "details": row.details,
        "metrics": row.metrics,
        "created_at": row.created_at.isoformat(),
    })


# ── AI Chatbot (mirip ApotekApps) ───────────────────────────────────────────────

def _build_chat_messages(user_msg, history, system_prompt):
    msgs = [{"role": "system", "content": system_prompt}]
    for h in history or []:
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_msg})
    return msgs


@login_required
@require_POST
def api_ai_chat(request):
    """Chat dengan AI router (OpenAI-compatible).

    Body JSON: {message, history?:[{role,content}], session_id?, source?}.
    Return: {reply, model, usage} atau {error}.
    """
    try:
        payload = json.loads(request.body or "{}")
    except Exception:
        return JsonResponse({"error": "Payload JSON tidak valid."}, status=400)

    message = (payload.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Pesan kosong."}, status=400)

    cfg = _effective_ai_config()
    if not cfg.enabled or not cfg.api_key or not cfg.base_url:
        return JsonResponse(
            {"error": "AI belum dikonfigurasi. Buka System Status untuk mengatur AI."},
            status=400,
        )

    history = payload.get("history") or []
    session_id = (payload.get("session_id") or "").strip()
    source = (payload.get("source") or "chatbot_widget").strip()
    messages = _build_chat_messages(message, history, cfg.system_prompt)

    try:
        reply, usage = call_ai_chat(messages, config=cfg, temperature=0.4)
    except RuntimeError as e:
        return JsonResponse({"error": str(e)}, status=502)

    AIChatLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        chat_type=AIChatLog.TYPE_CHAT,
        role="user", content=message,
        session_id=session_id, source=source, model=usage.get("model", ""),
    )
    AIChatLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        chat_type=AIChatLog.TYPE_CHAT,
        role="assistant", content=reply,
        session_id=session_id, source=source,
        model=usage.get("model", ""),
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
    )
    return JsonResponse({
        "reply": reply,
        "model": usage.get("model", ""),
        "usage": usage,
    })


@login_required
def api_ai_chat_history(request):
    """Riwayat chat per session_id (terbaru duluan, dikembalikan urut naik)."""
    session_id = request.GET.get("session_id", "").strip()
    chat_type = request.GET.get("chat_type", "").strip()
    qs = AIChatLog.objects.all()
    if session_id:
        qs = qs.filter(session_id=session_id)
    if chat_type:
        qs = qs.filter(chat_type=chat_type)
    rows = list(qs.order_by("created_at")[:100])
    items = [{"role": r.role, "content": r.content, "model": r.model,
              "created_at": r.created_at.isoformat()} for r in rows]
    return JsonResponse({"items": items, "count": len(items)})


@login_required
def api_ai_config(request):
    """Baca / perbarui konfigurasi AI (khusus staff/admin)."""
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"error": "Forbidden"}, status=403)
    cfg = AIConfig.get_active()
    if request.method == "POST":
        try:
            data = json.loads(request.body or "{}")
        except Exception:
            return JsonResponse({"error": "Payload JSON tidak valid."}, status=400)
        for fld in ("base_url", "model", "system_prompt"):
            if fld in data:
                setattr(cfg, fld, data[fld])
        if "api_key" in data and data["api_key"]:
            cfg.api_key = data["api_key"]
        if "enabled" in data:
            cfg.enabled = bool(data["enabled"])
        cfg.save()
        # jaga konsistensi dengan ConnectionConfig (menu Config)
        cc = _conn_cfg()
        if cc:
            cc.ai_enabled = cfg.enabled
            cc.ai_base_url = cfg.base_url
            cc.ai_model = cfg.model
            if data.get("api_key"):
                cc.ai_api_key = cfg.api_key
            cc.save()
        return JsonResponse({"ok": True, "config": _ai_config_public(cfg)})
    # baca: utamakan nilai dari ConnectionConfig (menu Config)
    cc = _conn_cfg()
    if cc:
        if cc.ai_base_url:
            cfg.base_url = cc.ai_base_url
        if cc.ai_model:
            cfg.model = cc.ai_model
        if cc.ai_api_key:
            cfg.api_key = cc.ai_api_key
        if cc.ai_enabled:
            cfg.enabled = True
        elif cc.ai_base_url and cc.ai_api_key:
            cfg.enabled = True
    return JsonResponse({"config": _ai_config_public(cfg)})


def _ai_config_public(cfg):
    return {
        "enabled": cfg.enabled,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "api_key_set": bool(cfg.api_key),
        "api_key_masked": cfg.mask_key(),
        "system_prompt": cfg.system_prompt,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


@login_required
def api_network_stream(request):
    """Server-Sent Events stream of live network traffic.

    Each emitted event corresponds to a real network event that just happened:
    an API request to ApotekApps (edge apps_api → module service, or nginx →
    apps_api) or a webhook received from ApotekApps (edge apps_api → monitor).
    The frontend turns these into animated "packets" that travel along the
    matching edges of the topology smartscape, so the data flow is visible.
    """
    import time as _time
    from django.http import StreamingHttpResponse

    # Map an API log to the topology edge it travels along.
    #   nginx → apps_api for the inbound hop, then apps_api → svc_<module>.
    def map_log_event(log):
        module = (log.endpoint.module if log.endpoint else
                  (log.path.strip("/").split("/")[0] if log.path else "common"))
        module = module or "common"
        return {
            "type": "api",
            "status": log.status,
            "method": log.method,
            "path": log.path,
            "module": module,
            "status_code": log.status_code,
            "response_time_ms": round(log.response_time_ms, 1) if log.response_time_ms else None,
            "edge_in": "nginx->apps_api",
            "edge_out": f"apps_api->svc_{module}",
            "at": log.created_at.isoformat(),
        }

    def map_webhook_event(wh):
        return {
            "type": "webhook",
            "event_type": wh.event_type,
            "status": wh.status,
            "source_ip": str(wh.source_ip) if wh.source_ip else None,
            "edge": "apps_api->monitor",
            "at": wh.received_at.isoformat(),
        }

    def event_generator():
        last_log_at = None
        last_wh_at = None
        # seed watermarks with the most recent existing records so we only
        # stream *new* events after the connection opens.
        l = APIRequestLog.objects.order_by("-created_at").first()
        w = WebhookEvent.objects.order_by("-received_at").first()
        last_log_at = l.created_at if l else None
        last_wh_at = w.received_at if w else None
        # initial heartbeat so the client knows the stream is alive
        yield "event: ready\ndata: {}\n\n"
        while True:
            new_logs = []
            if last_log_at is not None:
                new_logs = list(APIRequestLog.objects
                                .filter(created_at__gt=last_log_at)
                                .select_related("endpoint")
                                .order_by("created_at"))
            elif APIRequestLog.objects.exists():
                new_logs = list(APIRequestLog.objects
                                .select_related("endpoint")
                                .order_by("created_at")[:50])

            new_wh = []
            if last_wh_at is not None:
                new_wh = list(WebhookEvent.objects
                              .filter(received_at__gt=last_wh_at)
                              .order_by("received_at"))
            elif WebhookEvent.objects.exists():
                new_wh = list(WebhookEvent.objects.order_by("received_at")[:50])

            for log in new_logs:
                payload = json.dumps(map_log_event(log))
                yield f"event: packet\ndata: {payload}\n\n"
                last_log_at = log.created_at
            for wh in new_wh:
                payload = json.dumps(map_webhook_event(wh))
                yield f"event: packet\ndata: {payload}\n\n"
                last_wh_at = wh.received_at

            yield ": ping\n\n"
            _time.sleep(1)

    resp = StreamingHttpResponse(event_generator(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache, no-transform"
    resp["X-Accel-Buffering"] = "no"
    return resp


# ── Alerts / notifications ─────────────────────────────────────────────────────

@login_required
@require_POST
def api_alert_record(request):
    """Simpan alert dari frontend (mis. perubahan status topologi)."""
    try:
        payload = json.loads(request.body or "{}")
    except Exception:
        return JsonResponse({"error": "invalid json"}, status=400)

    level = payload.get("level", Alert.LEVEL_INFO)
    if level not in {Alert.LEVEL_INFO, Alert.LEVEL_WARNING,
                     Alert.LEVEL_CRITICAL, Alert.LEVEL_SUCCESS}:
        level = Alert.LEVEL_INFO
    title = (payload.get("title") or "").strip()[:200]
    message = (payload.get("message") or "").strip()
    source = (payload.get("source") or "topology").strip()[:60]
    if not title:
        return JsonResponse({"error": "title required"}, status=400)

    alert = Alert.objects.create(
        level=level, title=title, message=message, source=source,
    )
    return JsonResponse({"ok": True, "id": alert.id})


@login_required
def api_alerts_json(request):
    """Return recent alerts + unread count for the navbar bell."""
    alerts = Alert.objects.all()[:30]
    unread = Alert.objects.filter(is_read=False).count()
    return JsonResponse({
        "unread": unread,
        "alerts": [
            {
                "id": a.id, "level": a.level, "title": a.title,
                "message": a.message, "source": a.source,
                "is_read": a.is_read,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ],
    })


@login_required
@require_POST
def api_alert_mark_read(request):
    """Tandai satu / semua alert sudah dibaca."""
    try:
        payload = json.loads(request.body or "{}")
    except Exception:
        payload = {}
    aid = payload.get("id")
    if aid:
        Alert.objects.filter(id=aid, is_read=False).update(is_read=True)
    else:
        Alert.objects.filter(is_read=False).update(is_read=True)
    return JsonResponse({"ok": True, "unread": Alert.objects.filter(is_read=False).count()})


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
