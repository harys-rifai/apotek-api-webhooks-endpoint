"""
Isi tabel APIRequestLog & WebhookEvent dengan data palsu (fake) untuk demo.
Jalankan:
    python manage.py seed_fake
    python manage.py seed_fake --logs 200 --webhooks 50
    python manage.py seed_fake --clear        # hapus dulu sebelum isi
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.monitor.models import APIEndpoint, APIRequestLog, WebhookEvent


METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
TRIGGERS = ["manual", "scheduler", "webhook"]
WH_EVENTS = [
    "sale.created", "order.created", "order.updated", "medicine.created",
    "inventory.adjusted", "user.registered", "attendance.marked", "report.generated",
]
IPS = ["127.0.0.1", "192.168.1.10", "10.0.0.5", "172.16.0.23", "203.0.113.42"]
PAYLOAD_SAMPLES = {
    "sale.created": '{"sale_id": 1001, "total": 154000, "items": 3}',
    "order.created": '{"order_id": "ORD-204", "customer": "Budi", "amount": 89000}',
    "medicine.created": '{"medicine_id": 55, "name": "Paracetamol 500mg"}',
    "inventory.adjusted": '{"batch": "B-77", "delta": -12}',
    "user.registered": '{"user_id": 9, "username": "apoteker2"}',
    "attendance.marked": '{"user": "Sari", "shift": "pagi"}',
    "report.generated": '{"report": "daily-sales", "period": "2026-08-25"}',
}


class Command(BaseCommand):
    help = "Seed tabel monitor (APIRequestLog & WebhookEvent) dengan data palsu."

    def add_arguments(self, parser):
        parser.add_argument("--logs", type=int, default=150, help="Jumlah APIRequestLog palsu")
        parser.add_argument("--webhooks", type=int, default=40, help="Jumlah WebhookEvent palsu")
        parser.add_argument("--days", type=int, default=7, help="Sebar waktu dalam N hari terakhir")
        parser.add_argument("--clear", action="store_true", help="Hapus data lama sebelum mengisi")

    def handle(self, *args, **opts):
        n_logs = opts["logs"]
        n_wh = opts["webhooks"]
        days = max(1, opts["days"])

        if opts["clear"]:
            self.stdout.write("Menghapus data lama…")
            APIRequestLog.objects.all().delete()
            WebhookEvent.objects.all().delete()

        # pastikan ada endpoint untuk direferensikan
        if not APIEndpoint.objects.exists():
            self.stdout.write(self.style.WARNING("Tidak ada endpoint. Jalankan seed_endpoints dulu."))
            raise CommandError("APIEndpoint kosong.")
        endpoints = list(APIEndpoint.objects.all())

        now = timezone.now()
        logs_created = 0
        for _ in range(n_logs):
            ep = random.choice(endpoints)
            status = random.choices(
                [APIRequestLog.STATUS_SUCCESS, APIRequestLog.STATUS_FAIL, APIRequestLog.STATUS_ERROR],
                weights=[82, 12, 6],
            )[0]
            status_code = {
                APIRequestLog.STATUS_SUCCESS: random.choice([200, 200, 201, 204]),
                APIRequestLog.STATUS_FAIL: random.choice([400, 401, 403, 404, 422]),
                APIRequestLog.STATUS_ERROR: random.choice([500, 502, 503, 504]),
            }[status]
            attempt = 1 if status == APIRequestLog.STATUS_SUCCESS else random.randint(1, 3)
            rt = round(random.uniform(40, 3500), 1)
            ts = now - timedelta(
                days=random.randint(0, days - 1),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
                seconds=random.randint(0, 59),
            )
            err = ""
            if status != APIRequestLog.STATUS_SUCCESS:
                err = random.choice([
                    "Timeout menunggu respons", "Token JWT tidak valid", "Connection reset oleh peer",
                    "404 Not Found dari upstream", "ValidationError: field wajib kosong",
                ])
            APIRequestLog.objects.create(
                endpoint=ep,
                method=ep.method,
                path=ep.path,
                status_code=status_code,
                status=status,
                response_time_ms=rt,
                attempt=attempt,
                max_attempts=3,
                request_body="{}" if ep.method == "GET" else '{"sample": true}',
                response_body='{"ok": true}' if status == APIRequestLog.STATUS_SUCCESS else "",
                error_message=err,
                triggered_by=random.choice(TRIGGERS),
                created_at=ts,
            )
            logs_created += 1

        wh_created = 0
        for _ in range(n_wh):
            etype = random.choice(WH_EVENTS)
            status = random.choices(
                [WebhookEvent.STATUS_RECEIVED, WebhookEvent.STATUS_PROCESSED, WebhookEvent.STATUS_FAILED],
                weights=[30, 60, 10],
            )[0]
            ts = now - timedelta(
                days=random.randint(0, days - 1),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
                seconds=random.randint(0, 59),
            )
            proc = None
            if status in (WebhookEvent.STATUS_PROCESSED, WebhookEvent.STATUS_FAILED):
                proc = ts + timedelta(seconds=random.randint(1, 120))
            err = ""
            if status == WebhookEvent.STATUS_FAILED:
                err = random.choice([
                    "Payload tidak lengkap", "Signature webhook tidak cocok",
                    "Gagal menyimpan ke database", "Skema event tidak dikenal",
                ])
            payload = PAYLOAD_SAMPLES.get(etype, '{"ref": 1}')
            WebhookEvent.objects.create(
                event_type=etype,
                source_ip=random.choice(IPS),
                payload=payload,
                status=status,
                error_message=err,
                received_at=ts,
                processed_at=proc,
            )
            wh_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nSelesai: {logs_created} APIRequestLog & {wh_created} WebhookEvent dibuat."
        ))
