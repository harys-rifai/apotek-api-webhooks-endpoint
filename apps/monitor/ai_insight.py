"""Generate AI insights from real monitoring data and persist them.

The "AI" here is a rule-based analysis over live database metrics (request
volume, success rate, infra health, webhook activity, critical nodes). It is
deliberately dependency-free so it runs anywhere without an external LLM key.
"""
from django.utils import timezone
from datetime import timedelta

from .models import (
    APIRequestLog, WebhookEvent, AiInsight, APIEndpoint,
)


def _counts(since):
    total = APIRequestLog.objects.filter(created_at__gte=since).count()
    succ = APIRequestLog.objects.filter(created_at__gte=since, status="success").count()
    fail = APIRequestLog.objects.filter(created_at__gte=since, status__in=("fail", "error")).count()
    rate = round(succ / total * 100, 1) if total else 100.0
    return total, succ, fail, rate


def generate_ai_insight(force=False):
    """Build a fresh insight snapshot, persist it, and return the AiInsight row.

    If a recent insight (<60s) already exists and ``force`` is False, return the
    existing one to avoid duplicate rows on every poll.
    """
    now = timezone.now()
    if not force:
        recent = AiInsight.objects.first()
        if recent and (now - recent.created_at).total_seconds() < 60:
            return recent

    since = now - timedelta(minutes=5)
    total, succ, fail, rate = _counts(since)

    wh_total = WebhookEvent.objects.filter(received_at__gte=since).count()
    wh_fail = WebhookEvent.objects.filter(
        received_at__gte=since, status__in=("failed",)
    ).count()

    # module health (reuse the same 5m window the topology uses)
    modules = {}
    for ep in APIEndpoint.objects.filter(is_active=True):
        q = APIRequestLog.objects.filter(endpoint=ep, created_at__gte=since)
        t = q.count()
        if t:
            r = round(q.filter(status="success").count() / t * 100, 1)
            modules[ep.module] = min(modules.get(ep.module, 100.0), r)

    critical_mods = [m for m, r in modules.items() if r < 80]
    warning_mods = [m for m, r in modules.items() if 80 <= r < 95]

    details = []
    severity = AiInsight.SEVERITY_SUCCESS

    # 1. Traffic volume
    if total == 0:
        details.append({
            "label": "Traffic",
            "value": "Tidak ada request dalam 5 menit terakhir (idle).",
            "severity": AiInsight.SEVERITY_INFO,
        })
        severity = AiInsight.SEVERITY_INFO
    else:
        details.append({
            "label": "Traffic",
            "value": f"{total} request/5m · {succ} sukses · {fail} gagal.",
            "severity": AiInsight.SEVERITY_SUCCESS if fail == 0 else AiInsight.SEVERITY_WARNING,
        })
        if fail:
            severity = AiInsight.SEVERITY_WARNING

    # 2. Overall success rate
    details.append({
        "label": "Success rate",
        "value": f"{rate}% dalam 5 menit terakhir.",
        "severity": (AiInsight.SEVERITY_SUCCESS if rate >= 95
                     else AiInsight.SEVERITY_WARNING if rate >= 80
                     else AiInsight.SEVERITY_CRITICAL),
    })
    if rate < 95:
        severity = (AiInsight.SEVERITY_CRITICAL if rate < 80 else AiInsight.SEVERITY_WARNING)

    # 3. Webhooks
    if wh_total:
        details.append({
            "label": "Webhook",
            "value": f"{wh_total} event diterima · {wh_fail} gagal diproses.",
            "severity": AiInsight.SEVERITY_SUCCESS if wh_fail == 0 else AiInsight.SEVERITY_WARNING,
        })
        if wh_fail:
            severity = AiInsight.SEVERITY_WARNING
    else:
        details.append({
            "label": "Webhook",
            "value": "Belum ada webhook masuk di jendela 5 menit.",
            "severity": AiInsight.SEVERITY_INFO,
        })

    # 4. Module / service health
    if critical_mods:
        details.append({
            "label": "Service",
            "value": f"Kritis: {', '.join(sorted(critical_mods))}. Perlu perhatian segera.",
            "severity": AiInsight.SEVERITY_CRITICAL,
        })
        severity = AiInsight.SEVERITY_CRITICAL
    elif warning_mods:
        details.append({
            "label": "Service",
            "value": f"Menurun: {', '.join(sorted(warning_mods))}.",
            "severity": AiInsight.SEVERITY_WARNING,
        })
        if severity != AiInsight.SEVERITY_CRITICAL:
            severity = AiInsight.SEVERITY_WARNING
    else:
        details.append({
            "label": "Service",
            "value": "Semua modul layanan sehat (>=95%).",
            "severity": AiInsight.SEVERITY_SUCCESS,
        })

    # 5. Infrastructure (PostgreSQL, Redis, Media, Nginx, Python, System host)
    infra = _infra_health()
    critical_infra = []
    warning_infra = []
    if infra:
        worst_infra = AiInsight.SEVERITY_SUCCESS
        for comp in infra:
            sev = comp["severity"]
            if sev == AiInsight.SEVERITY_CRITICAL:
                worst_infra = AiInsight.SEVERITY_CRITICAL
                critical_infra.append(comp["name"])
            elif sev == AiInsight.SEVERITY_WARNING and worst_infra != AiInsight.SEVERITY_CRITICAL:
                worst_infra = AiInsight.SEVERITY_WARNING
                warning_infra.append(comp["name"])
            details.append({
                "label": comp["name"],
                "value": comp["value"],
                "severity": sev,
            })
        if worst_infra == AiInsight.SEVERITY_CRITICAL and severity != AiInsight.SEVERITY_CRITICAL:
            severity = AiInsight.SEVERITY_CRITICAL
        elif worst_infra == AiInsight.SEVERITY_WARNING and severity == AiInsight.SEVERITY_SUCCESS:
            severity = AiInsight.SEVERITY_WARNING

    # 6. AI suggestion / recommendation
    suggestion = _suggestion(total, rate, fail, wh_total, wh_fail,
                              critical_mods, warning_mods, critical_infra, warning_infra)
    details.append({
        "label": "Saran AI",
        "value": suggestion,
        "severity": severity,
    })

    summary = _headline(total, rate, wh_total, critical_mods, severity, critical_infra)

    row = AiInsight.objects.create(
        summary=summary,
        details=details,
        severity=severity,
        metrics={
            "requests_5m": total,
            "success_rate": rate,
            "failed": fail,
            "webhooks_5m": wh_total,
            "critical_modules": critical_mods,
            "warning_modules": warning_mods,
        },
    )
    return row


def _infra_health():
    """Probe backing infrastructure and return a list of component health dicts."""
    # imported lazily to avoid a circular import (views <-> ai_insight)
    from .views import (
        _probe_apotek_db, _probe_redis, _probe_media,
        _probe_nginx, _probe_python, _probe_system,
    )
    sev_map = {
        "healthy": AiInsight.SEVERITY_SUCCESS,
        "warning": AiInsight.SEVERITY_WARNING,
        "critical": AiInsight.SEVERITY_CRITICAL,
    }
    probes = [
        ("PostgreSQL", _probe_apotek_db),
        ("Redis", _probe_redis),
        ("Media Storage", _probe_media),
        ("Nginx", _probe_nginx),
        ("Python Runtime", _probe_python),
        ("System Host", _probe_system),
    ]
    out = []
    for name, fn in probes:
        try:
            res = fn()
            # each probe returns (status, detail[, meta])
            status = res[0]
            detail = res[1] if len(res) > 1 else ""
        except Exception as e:  # never let a probe crash the insight
            status, detail = "warning", f"probe error: {e}"
        out.append({
            "name": name,
            "value": detail,
            "severity": sev_map.get(status, AiInsight.SEVERITY_INFO),
        })
    # Monitor SQLite (this app's own DB) — always healthy if we got here
    out.append({
        "name": "Monitor SQLite",
        "value": "Basis data lokal Monitor aktif.",
        "severity": AiInsight.SEVERITY_SUCCESS,
    })
    return out


def _suggestion(total, rate, fail, wh_total, wh_fail, critical_mods, warning_mods,
                critical_infra=None, warning_infra=None):
    critical_infra = critical_infra or []
    warning_infra = warning_infra or []
    if total == 0:
        base = ("Jalankan `python manage.py simulate_traffic` untuk menghasilkan "
                "lalu lintas demo, atau pastikan ApotekApps mengirim request nyata "
                "ke endpoint yang dipantau.")
        if critical_infra:
            return (f"INFRA KRITIS: {', '.join(critical_infra)}. {base}")
        return base
    if critical_infra:
        return (f"Infrastruktur kritis: {', '.join(critical_infra)}. "
                "Periksa resource host (disk/memori/CPU load), bebaskan kapasitas, "
                "dan restart layanan terdampak jika perlu.")
    if critical_mods:
        return (f"Prioritaskan modul {', '.join(sorted(critical_mods))}: cek log error, "
                "naikkan resource, dan evaluasi dependensi (DB/redis). Aktifkan retry "
                "dengan backoff pada sisi ApotekApps.")
    if rate < 95 or fail:
        return ("Tingkat kegagalan meningkat. Periksa status DB/redis/nginx, tambah "
                "timeout/retry, dan pantau latency per-modul di halaman Endpoints.")
    if wh_fail:
        return ("Beberapa webhook gagal diproses. Validasi payload dan ulangi (replay) "
                "webhook yang failed dari panel Webhooks.")
    if warning_mods or warning_infra:
        parts = []
        if warning_mods: parts.append(f"modul {', '.join(sorted(warning_mods))}")
        if warning_infra: parts.append(f"infra {', '.join(warning_infra)}")
        return f"{' dan '.join(parts).capitalize()} mulai menurun. Pantau tren sebelum menyentuh ambang kritis."
    return ("Sistem dalam kondisi optimal. Tidak ada tindakan diperlukan; lanjutkan "
            "pemantauan rutin.")


def _headline(total, rate, wh_total, critical_mods, severity, critical_infra=None):
    critical_infra = critical_infra or []
    if critical_infra:
        return f"Infrastruktur kritis: {', '.join(critical_infra)}. Perlu perhatian segera."
    if total == 0:
        return "Sistem idle - tidak ada lalu lintas terdeteksi dalam 5 menit."
    if severity == AiInsight.SEVERITY_CRITICAL:
        return f"Peringatan kritis: {len(critical_mods)} modul bermasalah, success rate {rate}%."
    if severity == AiInsight.SEVERITY_WARNING:
        return f"Kondisi menurun: success rate {rate}%, {total} request/5m."
    return f"Sistem sehat: {total} request/5m, success rate {rate}%."
