"""
Generate live network traffic (APIRequestLog + WebhookEvent) secara berkala
agar halaman Topology · Network Stream menampilkan aktivitas realtime.

Jalankan (biarkan jalan di terminal terpisah):
    python manage.py simulate_traffic
    python manage.py simulate_traffic --rate 3 --max 0   # 3 event/detik, tanpa batas
    python manage.py simulate_traffic --duration 120     # berhenti setelah 120 dtk
"""
import random
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.monitor.models import APIEndpoint, APIRequestLog, WebhookEvent

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
WH_EVENTS = [
    "sale.created", "order.created", "order.updated", "medicine.created",
    "inventory.adjusted", "attendance.marked", "report.generated",
]
IPS = ["127.0.0.1", "192.168.1.10", "10.0.0.5", "203.0.113.42"]


class Command(BaseCommand):
    help = "Simulasikan traffic network secara live untuk demo Network Stream."

    def add_arguments(self, parser):
        parser.add_argument("--rate", type=float, default=2.0,
                            help="Rata-rata event per detik (default 2).")
        parser.add_argument("--duration", type=int, default=0,
                            help="Durasi dalam detik (0 = jalan terus).")
        parser.add_argument("--max", type=int, default=0,
                            help="Jumlah maksimal event (0 = tanpa batas).")

    def handle(self, *args, **opts):
        rate = max(0.1, opts["rate"])
        duration = opts["duration"]
        max_ev = opts["max"]
        delay = 1.0 / rate

        if not APIEndpoint.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Tidak ada endpoint. Jalankan `python manage.py seed_endpoints` dulu."))
            return

        endpoints = list(APIEndpoint.objects.all())
        start = timezone.now()
        count = 0
        self.stdout.write(self.style.SUCCESS(
            f"Memulai simulasi traffic @ {rate}/detik (Ctrl+C untuk berhenti)…"))

        try:
            while True:
                if duration and (timezone.now() - start).total_seconds() > duration:
                    break
                if max_ev and count >= max_ev:
                    break

                # ~70% API request, ~30% webhook
                if random.random() < 0.7:
                    ep = random.choice(endpoints)
                    status = random.choices(
                        ["success", "success", "success", "fail", "error"],
                        weights=[70, 12, 10, 5, 3])[0]
                    APIRequestLog.objects.create(
                        endpoint=ep,
                        method=random.choice(METHODS),
                        path=ep.path,
                        status_code=200 if status == "success" else (400 if status == "fail" else 500),
                        status=status,
                        response_time_ms=round(random.uniform(20, 1800), 1),
                        attempt=1, max_attempts=3,
                        triggered_by=random.choice(["manual", "scheduler"]),
                    )
                else:
                    ev = random.choice(WH_EVENTS)
                    WebhookEvent.objects.create(
                        event_type=ev,
                        source_ip=random.choice(IPS),
                        status="received",
                        payload='{"simulated": true}',
                    )
                count += 1
                time.sleep(delay)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nDihentikan."))

        self.stdout.write(self.style.SUCCESS(f"Selesai. {count} event dibuat."))
