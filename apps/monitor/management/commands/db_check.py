"""
Cek integritas database SQLite Monitor tanpa mengubah data.

Jalankan PRAGMA integrity_check dan foreign_key_check. Keluar dengan
status 0 bila sehat, 1 bila terdeteksi masalah (cocok untuk cron + alert).
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Cek integritas db.sqlite3 (integrity_check + foreign_key_check)."

    def handle(self, *args, **opts):
        problems = []

        with connection.cursor() as cur:
            cur.execute("PRAGMA integrity_check")
            rows = cur.fetchall()
        if rows and rows[0][0] != "ok":
            problems.append("integrity_check: " + "; ".join(r[0] for r in rows))

        try:
            with connection.cursor() as cur:
                cur.execute("PRAGMA foreign_key_check")
                fk = cur.fetchall()
            if fk:
                problems.append(f"foreign_key_check: {len(fk)} pelanggaran")
        except Exception as e:
            self.stderr.write(f"(foreign_key_check dilewati: {e})")

        if problems:
            self.stderr.write("DATABASE TIDAK SEHAT:")
            for p in problems:
                self.stderr.write("  - " + p)
            self.stderr.write("Saran: restore dari snapshot terbaru (python manage.py db_restore).")
            raise SystemExit(1)

        self.stdout.write("Database sehat: integrity_check=ok.")
