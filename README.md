# ApotekMonitor

API Monitoring Dashboard untuk [ApotekApps](https://github.com/harys-rifai/ApotekApps) — memantau kesehatan endpoint, request logs, webhook events, latency, dan business success rate secara realtime.

---

## Tampilan

| Dashboard | Endpoints | Logs |
|-----------|-----------|------|
| KPI cards, charts, tabel | List endpoint + ping | Filter & pagination |

---

## Fitur

- **Dashboard realtime** — KPI cards (total, success, fail, error, success rate, avg latency)
- **Request Volume Chart** — stacked bar per hari (7 / 14 / 30 hari)
- **Status Distribution** — donut chart success vs fail vs error
- **Latency Chart** — line chart avg response time per hari
- **Top Endpoints Table** — ranking endpoint paling banyak dipanggil + pagination
- **Slowest Endpoints** — endpoint dengan avg latency tertinggi
- **Request Logs** — filter status, method, path + pagination client-side
- **Webhook Receiver** — endpoint `POST /webhook/receive/` untuk menerima event dari sistem eksternal
- **Endpoint Ping** — test langsung ke ApotekApps API dengan satu klik
- **JWT Auto-Refresh** — token dikelola otomatis (login → refresh → re-login)
- **Retry + Rate Limiting** — max 3 retry dengan exponential backoff, throttle 60 req/menit
- **Dark Theme** — Neon Dark UI, identik dengan ApotekApps

---

## Requirement

| Software | Versi |
|----------|-------|
| Python   | 3.11+ |
| Django   | 4.2.x |
| requests | 2.32.x |

> ApotekApps harus berjalan di `http://127.0.0.1:8000` agar ping & monitoring berfungsi.

---

## Instalasi

```bash
# 1. Clone repo
git clone https://github.com/harys-rifai/apotek-api-webhooks-endpoint.git
cd apotek-api-webhooks-endpoint

# 2. Salin konfigurasi
cp .env.example .env

# 3. Jalankan (otomatis buat venv, install deps, migrate, buat admin)
sh run.sh
```

Server berjalan di **http://127.0.0.1:8090**

---

## Konfigurasi `.env`

```env
SECRET_KEY=ganti-dengan-secret-key-aman
DEBUG=True
ALLOWED_HOSTS=*

# URL base API ApotekApps (tanpa trailing slash)
APOTEK_API_BASE_URL=http://127.0.0.1:8000/api

# Kredensial login ke ApotekApps untuk token management
APOTEK_ADMIN_USERNAME=admin
APOTEK_ADMIN_PASSWORD=admin
```

---

## Login Default

| Field    | Value   |
|----------|---------|
| Username | `admin` |
| Password | `admin` |

Login di **http://127.0.0.1:8090/login/**

---

## Struktur Project

```
ApotekMonitor/
├── apps/
│   ├── accounts/          # Login / logout
│   └── monitor/
│       ├── models.py      # APIEndpoint, APIRequestLog, WebhookEvent
│       ├── services.py    # HTTP client (JWT, retry, rate-limit)
│       ├── views.py       # Dashboard, logs, ping, stats JSON, webhook receiver
│       ├── urls.py
│       └── management/commands/
│           └── seed_endpoints.py   # Isi 33 endpoint ApotekApps
├── config/
│   ├── settings.py
│   └── urls.py
├── templates/
│   ├── base.html
│   ├── accounts/login.html
│   ├── monitor/
│   │   ├── dashboard.html
│   │   ├── endpoints.html
│   │   ├── endpoint_detail.html
│   │   ├── logs.html
│   │   └── webhooks.html
│   └── partials/
│       ├── sidebar.html
│       └── navbar.html
├── static/
│   ├── css/
│   │   ├── theme.css      # Neon dark theme (shared dengan ApotekApps)
│   │   └── main.css       # Komponen spesifik ApotekMonitor
│   └── js/main.js
├── manage.py
├── requirements.txt
├── run.sh
├── push.sh
└── .env.example
```

---

## Halaman & URL

| URL | Deskripsi |
|-----|-----------|
| `/` | Dashboard utama |
| `/endpoints/` | Daftar semua endpoint + ping |
| `/endpoints/<id>/` | Detail endpoint + log history |
| `/logs/` | Semua request log (filter + pagination) |
| `/webhooks/` | Daftar webhook event yang diterima |
| `/api/ping/<id>/` | Ping endpoint (JSON) |
| `/api/stats/` | Data chart (JSON) |
| `/webhook/receive/` | Terima event webhook (POST) |
| `/login/` | Halaman login |
| `/admin/` | Django admin |

---

## Seed Endpoint

Untuk mengisi 33 endpoint ApotekApps ke database:

```bash
python manage.py seed_endpoints
```

---

## Webhook

Kirim event dari sistem lain ke ApotekMonitor:

```bash
curl -X POST http://127.0.0.1:8090/webhook/receive/ \
  -H "Content-Type: application/json" \
  -d '{"event": "stok_habis", "medicine": "Paracetamol", "qty": 0}'
```

Event tersimpan di tabel `WebhookEvent` dan tampil di halaman `/webhooks/`.

---

## Tech Stack

- **Backend** — Django 4.2, SQLite
- **HTTP Client** — requests + urllib3 Retry
- **Auth** — Django session (monitor) + JWT auto-managed (ApotekApps API)
- **Frontend** — Django templates, Chart.js 4.4, Font Awesome 6.5
- **Theme** — Neon Dark (shared dengan ApotekApps)

---

## Push ke GitHub

```bash
sh push.sh
```

> Remote: `https://github.com/harys-rifai/apotek-api-webhooks-endpoint.git`
