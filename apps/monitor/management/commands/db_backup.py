"""
Backup & restore utilitas untuk database SQLite Monitor.

SQLite rentan korupsi bila terjadi unclean shutdown, filesystem jaringan, atau
write concurrency tinggi. Command ini memberi jaminan cepat:

  * db_backup  -> checkpoint WAL lalu salin db.sqlite3 menjadi snapshot
                 timestamp (gzip). Aman dijalankan berkala (cron).
  * db_check   -> PRAGMA integrity_check / foreign_key_check untuk deteksi
                 korupsi dini. Keluar 1 bila bermasalah (cocok untuk alert).
  * db_restore -> pulihkan dari snapshot (cek integritas dulu, backup darurat
                 file live, lalu tulis ulang).

Snapshot di <BASE_DIR>/backups/db/. Contoh cron:
  */30 * * * *  python manage.py db_backup --rotate 48
  0 3 * * *     python manage.py db_check
"""
import os
import gzip
import glob

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import connection


def _db_path():
    return str(settings.DATABASES["default"]["NAME"])


def _backup_dir():
    d = os.path.join(settings.BASE_DIR, "backups", "db")
    os.makedirs(d, exist_ok=True)
    return d


def _snapshot_path(ts):
    return os.path.join(_backup_dir(), f"monitor_{ts}.sqlite3.gz")


def _check_integrity_file(path):
    try:
        import sqlite3
    except Exception:
        return True, "sqlite3 tidak tersedia"
    try:
        con = sqlite3.connect(path)
        res = con.execute("PRAGMA integrity_check").fetchall()
        con.close()
        return (res and res[0][0] == "ok"), "; ".join(r[0] for r in res)
    except Exception as e:
        return False, str(e)


class Command(BaseCommand):
    help = "Snapshot db.sqlite3 Monitor (gzip) sebagai backup file-level."

    def add_arguments(self, parser):
        parser.add_argument("--rotate", type=int, default=24,
                            help="Jumlah snapshot terbaru dipertahankan (default 24).")
        parser.add_argument("--no-rotate", action="store_true",
                            help="Jangan hapus snapshot lama.")

    def handle(self, *args, **opts):
        name = _db_path()
        if not os.path.exists(name):
            raise CommandError(f"Database tidak ditemukan: {name}")

        # checkpoint WAL -> db.sqlite3 agar semua data ada di file utama
        try:
            with connection.cursor() as cur:
                cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            self.stderr.write(f"(wal_checkpoint dilewati: {e})")

        ts = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        dest = _snapshot_path(ts)
        with open(name, "rb") as f, gzip.open(dest, "wb", compresslevel=6) as gz:
            gz.writelines(f)
        self.stdout.write(f"Snapshot dibuat: {dest} ({os.path.getsize(dest)//1024} KB)")

        if not opts["no_rotate"]:
            snaps = sorted(glob.glob(os.path.join(_backup_dir(), "monitor_*.sqlite3.gz")))
            while len(snaps) > opts["rotate"]:
                old = snaps.pop(0)
                os.remove(old)
                self.stdout.write(f"Hapus snapshot lama: {old}")
