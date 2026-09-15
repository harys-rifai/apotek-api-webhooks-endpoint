from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from urllib.parse import urlunparse, urlparse


ENCRYPTED_PREFIX = "enc:"


class SecretEncryptionError(Exception):
    pass


def _fernet() -> Fernet:
    key = getattr(settings, "DB_ENCRYPTION_KEY", "").strip()
    if not key:
        key_file = getattr(settings, "DB_ENCRYPTION_KEY_FILE", "").strip()
        if key_file:
            path = Path(key_file)
            if not path.is_absolute():
                path = Path(settings.BASE_DIR) / path
            try:
                key = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise SecretEncryptionError(
                    f"Tidak bisa membaca kunci enkripsi {path}: {exc}"
                ) from exc
    if not key:
        raise SecretEncryptionError(
            "DB_ENCRYPTION_KEY belum diatur. Jalankan "
            "`python manage.py generate_encryption_key --write`."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (TypeError, ValueError) as exc:
        raise SecretEncryptionError("DB_ENCRYPTION_KEY tidak valid.") from exc


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_secret(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text or is_encrypted(text):
        return text
    return ENCRYPTED_PREFIX + _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_secret(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if not is_encrypted(text):
        return text
    try:
        return _fernet().decrypt(text[len(ENCRYPTED_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise SecretEncryptionError(
            "Gagal membuka credential. Periksa DB_ENCRYPTION_KEY atau file kuncinya."
        ) from exc


def mask_secret(value, leading=2, trailing=2) -> str:
    try:
        text = decrypt_secret(value)
    except SecretEncryptionError:
        return "****"
    if not text:
        return ""
    if len(text) <= max(leading, trailing) + 2:
        return "*" * min(8, len(text))
    return text[:leading] + "****" + text[-trailing:]


def mask_url(value) -> str:
    try:
        text = decrypt_secret(value)
    except SecretEncryptionError:
        return "****"
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.password:
        return text
    password = parsed.password
    masked = password[:2] + "****" + password[-2:] if len(password) > 4 else "****"
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port else ""
    username = parsed.username
    if username:
        username = username if ":" not in username else username.split(":", 1)[0]
        netloc = f"{username}:{masked}@{hostname}{port}"
    else:
        netloc = f"{masked}@{hostname}{port}"
    return urlunparse(parsed._replace(netloc=netloc))
