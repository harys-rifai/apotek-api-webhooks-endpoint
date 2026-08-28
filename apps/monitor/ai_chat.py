"""AI chatbot caller — OpenAI-compatible router (sama seperti ApotekApps).

Memanggil endpoint ``/chat/completions`` milik router AI (mis. LiteLLM /
OpenAI). Tidak menambah dependency baru; hanya memakai ``urllib`` bawaan.
"""
import json
import logging
import urllib.error
import urllib.request

from .models import AIConfig

logger = logging.getLogger(__name__)


def call_ai_chat(messages, config=None, temperature=0.4):
    """Panggil router AI OpenAI-compatible.

    Returns tuple ``(reply_text, usage_dict)`` dengan ``usage_dict`` berisi
    ``model``, ``prompt_tokens``, ``completion_tokens``. Raise RuntimeError
    bila gagal / belum dikonfigurasi.
    """
    config = config or AIConfig.get_active()
    if not config.enabled or not config.base_url or not config.api_key:
        raise RuntimeError("AI belum dikonfigurasi atau dinonaktifkan.")

    url = config.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.model or "gpt-4o",
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        reply = body["choices"][0]["message"]["content"].strip()
        usage = body.get("usage", {}) or {}
        usage_info = {
            "model": body.get("model", config.model or ""),
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        }
        return reply, usage_info
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"AI router error {e.code}: {detail}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Gagal menghubungi AI router: {e}")
