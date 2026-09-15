from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Generate a Fernet key for encrypting credentials stored in SQLite."

    def add_arguments(self, parser):
        parser.add_argument(
            "--write",
            action="store_true",
            help="Write the key to DB_ENCRYPTION_KEY_FILE instead of printing it.",
        )

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode("ascii")
        if not options["write"]:
            self.stdout.write(key)
            return

        key_file = getattr(settings, "DB_ENCRYPTION_KEY_FILE", "").strip()
        if not key_file:
            raise CommandError("DB_ENCRYPTION_KEY_FILE belum diatur.")
        path = Path(key_file)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(key + "\n", encoding="utf-8")
        except OSError as exc:
            raise CommandError(f"Gagal menulis kunci enkripsi: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Kunci enkripsi disimpan di {path}"))
