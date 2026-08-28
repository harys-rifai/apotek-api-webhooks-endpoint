"""
Pulihkan database Monitor dari snapshot hasil `db_backup`.

Alur aman:
  1. Cek integritas snapshot sebelum dipakai.
  2. Backup darurat file live saat ini (cadangan jika restore bermasalah).
  3. Tulis ulang db.sqlite3 dari snapshot, hapus -wal/-shm lama.
  4. Verifikasi integritas hasil restore.

Penggunaan:
  python manage.py db_restore                 # snapshot terbaru
  python manage.py db_restore --file backups/db/monitor_20260828_120000.sqlite3.gz
"""
import os
import gzip
import glob
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


def _db_path():
    return str(settings.DATABASES["default"]["NAME"])


def _backup_dir():
    return os.path.join(settings.BASE_DIR, "backups", "db")


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
    help = "Restore database Monitor dari snapshot db_backup."

    def add_arguments(self, parser):
        parser.add_argument("--file", default="", help="Path snapshot eksplisit.")
        parser.add_argument("--yes", action="store_true", help="Lewati konfirmasi.")

    def handle(self, *args, **opts):
        name = _db_path()
        d = _backup_dir()

        if opts["file"]:
            snap = opts["file"]
            if not os.path.exists(snap):
                raise CommandError(f"Snapshot tidak ditemukan: {snap}")
        else:
            snaps = sorted(glob.glob(os.path.join(d, "monitor_*.sqlite3.gz")))
            if not snaps:
                raise CommandError("Tidak ada snapshot. Jalankan `db_backup` dulu.")
            snap = snaps[-1]

        # 1. ekstrak ke temp & cek integritas
        import tempfile
        tmp = os.path.join(d, "_restore_tmp.sqlite3")
        with gzip.open(snap, "rb") as gz, open(tmp, "wb") as out:
            out.writelines(gz)
        ok, msg = _check_integrity_file(tmp)
        if not ok:
            os.remove(tmp)
            raise CommandError(f"Snapshot korupsi, batal restore: {msg}")

        # 2. backup darurat file live
        if os.path.exists(name):
            ts = timezone.localtime().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(name, name + f".prerestore_{ts}")
        # hapus wal/shm lama agar tidak bentrok
        for ext in (".wal", ".shm"):
            p = name + ext
            if os.path.exists(p):
                os.remove(p)

        # 3. tulis db.sqlite3 dari snapshot
        shutil.move(tmp, name)
        self.stdout.write(f"Database dipulihkan dari: {snap}")

        # 4. verifikasi
        ok2, msg2 = _check_integrity_file(name)
        if not ok2:
            raise CommandError(f"Restore selesai tapi integritas gagal: {msg2}")
        self.stdout.write("Verifikasi integritas: ok. Selesai.")
