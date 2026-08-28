# DEVELOPMENT.md — Panduan Pengembangan ApotekMonitor

Dokumen ini berisi arsitektur internal, alur data, dan *roadmap* pengembangan
ApotekMonitor. Tujuannya agar siapapun bisa mengembangkan aplikasi ini tanpa
harus membedah seluruh kode dari nol.

---

## 1. Ikhtisar Arsitektur

ApotekMonitor adalah **orchestration & observability layer** yang berdiri di
depan [ApotekApps](https://github.com/harys-rifai/ApotekApps). Ia tidak menyimpan
data bisnis — ia *mengamati* ApotekApps: memanggil endpoint-nya, mencatat hasil,
menerima webhook, lalu memvisualisasikan kesehatan & topologi secara realtime.

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (Operator)                                          │
│  ├─ Dashboard  (Chart.js)                                    │
│  ├─ Topology   (SVG smartscape + SSE live network stream)    │
│  └─ Logs / Webhooks / Alerts / Deliveries                    │
└───────────────┬───────────────────────────┬─────────────────┘
                │  HTTP (session auth)        │  SSE (EventSource)
                ▼                            │
        ┌───────────────┐                    │
        │  Django 4.2   │  ← /api/* (JSON)   │
        │  :8090        │  ← /api/network/   │
        └──────┬────────┘     stream/ (SSE)  │
               │ call_api()                  │
               ▼                             │
        ┌───────────────┐                    │
        │ services.py   │ ── HTTP/JWT ──▶ ApotekApps :8000
        │ (retry, rl,   │ ◀── webhook ──── ApotekApps :8000
        │  token mgmt)  │
        └──────┬────────┘
               │ ORM
               ▼
        ┌───────────────┐
        │ SQLite        │  APIEndpoint · APIRequestLog · WebhookEvent · Alert
        └───────────────┘
```

**Kunci desain:** semua komunikasi ke ApotekApps melewati `services.call_api()`
(satu pintu), sehingga retry, rate-limit, dan JWT terpusat. Semua data observasi
disimpan di SQLite lewat model di `apps/monitor/models.py`.

---

## 2. Struktur Module `apps/monitor`

| File | Tanggung jawab |
|------|----------------|
| `models.py` | `APIEndpoint`, `APIRequestLog`, `WebhookEvent`, `Alert` |
| `services.py` | HTTP client: `call_api()`, JWT cache, rate-limit, retry/backoff |
| `views.py` | Halaman + API JSON + SSE + health probes + webhook receiver |
| `urls.py` | Routing |
| `management/commands/seed_endpoints.py` | Isi daftar endpoint ApotekApps |
| `management/commands/seed_fake.py` | Generate log/webhook dummy untuk demo |

### 2.1 Models

- **APIEndpoint** — definisi endpoint yang dipantau (`path`, `method`, `module`).
  `module` digunakan sebagai identitas "microservice" di topologi (`svc_<module>`).
- **APIRequestLog** — satu baris per pemanggilan `call_api()`. Menyimpan
  status, latency, attempt, snapshot request/response. **Ini sumber data utama
  untuk chart, log, dan network stream.**
- **WebhookEvent** — event masuk dari ApotekApps via `POST /webhook/receive/`.
- **Alert** — notifikasi perubahan status (critical/warning/recovered) dari
  topologi. Ditampilkan di navbar bell & halaman `/alerts/`.

### 2.2 services.py — Pintu Komunikasi

`call_api(method, path, *, body, params, max_attempts, triggered_by,
save_log, endpoint_obj)`:

1. Cek rate-limit (60 req/menit, in-memory).
2. Ambil JWT (cache → refresh → login ulang, via `_token_lock`).
3. Kirim via `requests.Session` dengan `Retry` (5xx, backoff eksponensial).
4. Klasifikasi status: `success` (2xx) / `fail` (4xx) / `error` (5xx/timeout/conn).
5. Simpan `APIRequestLog` (kecuali `save_log=False`).

> **Catatan pengembangan:** token cache bersifat *per-process* (Django dev server
> single-process). Bila kelak di-deploy multi-worker (gunicorn), pindahkan cache
> token ke Redis atau pakai `django-cache`.

---

## 3. Alur Data Realtime

### 3.1 Polling (setiap 3 detik)

```
Browser ──GET /api/topology/──▶ api_topology_json()
                                  ├─ health probes (DB, Redis, media, nginx,
                                  │  python, system)
                                  ├─ agregasi APIRequestLog (5 menit terakhir)
                                  └─ bentuk nodes + edges JSON
        ◀── JSON {nodes, edges, overall_success_rate, infra} ──┘
```

Frontend (`topology.html`) merender SVG smartscape, menyimpan posisi node
(user-draggable), dan memanggil `emitNotifications()` bila status node/edge
berubah (lalu menyimpan via `POST /api/alert/record/`).

### 3.2 Streaming (SSE — push event)

```
Browser ──EventSource /api/network/stream/──▶ api_network_stream()
        ◀── event: ready
        ◀── : ping  (heartbeat 1 detik)
        ◀── event: packet  {type, status, method, path, module/event_type,
                             edge_in, edge_out / edge, ...}   ← tiap event baru
```

`api_network_stream` (views.py:886) adalah generator `StreamingHttpResponse`.
Ia menyimpan *watermark* waktu terakhir, lalu tiap detik mengecek
`APIRequestLog`/`WebhookEvent` yang `created_at/received_at` lebih baru dari
watermark, dan men-stream-nya sebagai event `packet`.

Pemetaan edge (di frontend `handlePacket`):

| Event | Edge yang dilalui paket |
|-------|--------------------------|
| API request | `nginx → apps_api` lalu `apps_api → svc_<module>` |
| Webhook | `apps_api → monitor` |

Paket dirender sebagai `<circle>` yang bergerak sepanjang bezier edge (fungsi
`spawnPacket` + `pointOnPath` di `topology.html`), warna mengikuti status
(hijau sukses, merah gagal, ungu webhook).

> **Keuntungan SSE di sini:** satu koneksi HTTP terbuka, otomatis reconnect,
> tanpa dependency ekstra (tidak perlu Channels/Redis). Cocok untuk volume
> event menengah.

---

## 4. Health Probes

Fungsi `_probe_*` di `views.py` melakukan pengecekan nyata terhadap backing
service ApotekApps:

- `_probe_apotek_db()` — TCP ke host:port, lalu `psycopg` connect bila ada driver.
- `_probe_redis()` — parse `REDIS_URL`, cek ping/latency.
- `_probe_media()` — ukur filesystem media (size, file count).
- `_probe_nginx()` — cek port 80/443.
- `_probe_python()` — versi interpreter + runtime ApotekApps.
- `_probe_system()` — disk/mem/load via `psutil`.

Hasil probe mengisi node infrastruktur di topologi dan field `infra` di JSON.

---

## 5. Cara Menambah Fitur

### 5.1 Menambah halaman baru

1. Buat template di `templates/monitor/<nama>.html` (extends `base.html`).
2. Tambah view di `views.py` (biasanya `@login_required`).
3. Daftarkan route di `urls.py`.
4. Tambah link di `templates/partials/sidebar.html` dengan
   `{% url 'nama_url' %}` dan `active_menu`.

### 5.2 Menambah metric ke topologi

- Node baru: tambah `nodes.append({...})` di `api_topology_json()`.
- Edge baru: tambah `edges.append({from, to, ...})` dan pasangkan pemetaan
  `CORE` di `placeNode()` (frontend) agar posisinya tetap.
- Metric per-node: tambahkan field ke dict node, lalu tampilkan di `drawNode()`
  (variabel `metricTxt`) dan tooltip.

### 5.3 Menambah sumber event ke network stream

Edit `event_generator()` di `api_network_stream`:

```python
# contoh: stream event dari model lain
new_x = list(MyModel.objects.filter(created_at__gt=last_x_at))
for x in new_x:
    yield f"event: packet\ndata: {json.dumps({...})}\n\n"
    last_x_at = x.created_at
```

Lalu tambahkan pemetaan edge di `handlePacket()` frontend bila perlu animasi
di topologi.

---

## 6. Roadmap Pengembangan

Berikut ide pengembangan terurut berdasarkan dampak & effort. Silakan dikerjakan
bertahap.

### 6.1 Observability & Alerting (High impact)
- [ ] **Threshold-based alerting** — aturan (mis. latency > 2s, success rate < 80%)
      dievaluasi di `api_topology_json` / cron, bukan hanya flip-flop status.
- [ ] **Notification channels** — kirim alert ke Email / Telegram / Slack
      (model `NotificationChannel` + task pengirim).
- [ ] **Alert acknowledge & history filter** — filter di `/alerts/` by level/source.
- [ ] **SLO / error budget** — definisikan target per module, tampilkan burn rate.

### 6.2 Realtime & Skalabilitas
- [ ] **Redis-backed token cache + rate-limit** agar aman di multi-worker.
- [ ] **Backpressure pada SSE** — batasi packet rate bila frontend lambat.
- [ ] **WebSocket (Django Channels)** bila event sangat tinggi & butuh duplex.
- [ ] **Historical replay** — stream ulang window 5/15 menit untuk demo tanpa traffic.

### 6.3 Data & Analitik
- [ ] **Per-endpoint SLA dashboard** — uptime %, p95/p99 latency.
- [ ] **Anomaly detection** — deteksi lonjakan latency/error otomatis (statistical).
- [ ] **Export** — CSV/PDF untuk log & laporan harian.
- [ ] **Retention policy** — purge `APIRequestLog` lama ke cold storage / agregat.

### 6.4 Topology Enhancement
- [ ] **Drill-down node** — klik node → modal detail (recent errors, p95, deps).
- [ ] **Force-directed layout** alternatif dari posisi statis `CORE`.
- [ ] **Multi-cluster / env switcher** (dev/staging/prod) dengan konfigurasi terpisah.
- [ ] **Synthetic monitoring** — jadwalkan `call_api` berkala (Celery beat) agar
      topologi punya traffic walau tidak ada user.

### 6.5 Infrastruktur & DX
- [ ] **Dockerfile + docker-compose** (Monitor + ApotekApps + Postgres + Redis).
- [ ] **CI** — lint (ruff/flake8) + smoke test (`manage.py test`).
- [ ] **Settings terpisah** (dev/prod) via `config/settings/`.
- [ ] **OpenTelemetry** — ekspor trace/metric ke collector eksternal.

---

## 7. Konvensi & Catatan

- **Jangan** membuat HTTP call ke ApotekApps di luar `services.call_api()` agar
  retry/rate-limit/JWT konsisten.
- **Semua** halaman butuh `@login_required` kecuali `webhook_receiver` (pakai
  token/shared-secret di level aplikasi, bukan session).
- Frontend smartscape murni **vanilla JS + SVG** (tanpa framework) — jaga agar
  tetap framework-free untuk kemudahan deploy.
- Warna status terpusat di objek `COLOR` (`topology.html`) — tambah di situ bila
  ada status baru.
- Output SSE harus persis format `event: <n>\ndata: <json>\n\n` (dua newline).

---

## 8. Quick Commands

```bash
# dev server
sh run.sh

# seed
python manage.py seed_endpoints
python manage.py seed_fake

# uji SSE cepat (butuh session — pakai browser)
# buka http://127.0.0.1:8090/topology/ lalu lihat panel "Network Stream"

# cek pola request via curl (JSON, butuh login cookie)
curl -b "sessionid=..." http://127.0.0.1:8090/api/topology/
```
