# ApotekMonitor

![ApotekMonitor](img/monitoringSystem.png)

Observability & orchestration dashboard for [ApotekApps](https://github.com/harys-rifai/ApotekApps) — monitors endpoint health, request logs, webhook events, latency, and business success rate, plus a **realtime infrastructure topology** with a **live network stream**.

---

## Overview

| Dashboard | Topology · Smartscape | Endpoints | Logs |
|-----------|----------------------|-----------|------|
| KPI cards, charts, tables | Node + edge map with live network stream | Endpoint list + ping | Filter & pagination |

---

## Features

- **Realtime Dashboard** — KPI cards (total, success, fail, error, success rate, avg latency)
- **Request Volume Chart** — stacked bar per day (7 / 14 / 30 days)
- **Status Distribution** — donut chart success vs fail vs error
- **Latency Chart** — line chart of average response time per day
- **Top Endpoints Table** — most-called endpoints ranking + pagination
- **Slowest Endpoints** — endpoints with the highest average latency
- **Topology · Smartscape** — Dynatrace-style map of infrastructure nodes (PostgreSQL, Redis, Media, Nginx, Python, System Host, ApotekApps API, OrchestrationApps) and per-module microservices, with edges representing relationships & traffic.
- **Live Network Stream** — *real-time* network traffic via Server-Sent Events (SSE). Every new API request or webhook spawns a "packet" that travels along the matching topology edge, with a side feed panel (pkts, pkts/s, requests, webhooks).
- **Brand Icons** — nodes use accurate brand SVGs (PostgreSQL, Redis, SQLite, Nginx via official Simple Icons paths; other nodes via Font Awesome), all rendered at a uniform size without hexagon badges.
- **Health Probes** — real checks against PostgreSQL, Redis, media storage, Nginx, the Python runtime, and the host system.
- **Request Logs** — filter by status, method, path + client-side pagination
- **Webhook Receiver** — `POST /webhook/receive/` to ingest events from external systems
- **Endpoint Ping** — one-click direct call to the ApotekApps API
- **JWT Auto-Refresh** — tokens managed automatically (login → refresh → re-login)
- **Retry + Rate Limiting** — up to 3 retries with exponential backoff, throttled to 60 req/min
- **Alerts** — topology status-change notifications (critical / warning / recovered) stored and shown in the navbar
- **Dark Theme** — Neon Dark UI, matching ApotekApps

---

## Requirements

| Software | Version |
|----------|---------|
| Python   | 3.11+   |
| Django   | 4.2.x   |
| requests | 2.32.x  |
| psutil   | 7.2.x   |
| python-decouple | 3.8.x |

> ApotekApps must be running at `http://127.0.0.1:8000` for ping, probing, and monitoring to work.

---

## Installation

```bash
# 1. Clone repo
git clone https://github.com/harys-rifai/ApotekMonitor.git
cd ApotekMonitor

# 2. Copy configuration
cp .env.example .env

# 3. Run (auto-creates venv, installs deps, migrates, creates admin)
sh run.sh
```

Server runs at **http://127.0.0.1:8090**

---

## Configuration `.env`

```env
SECRET_KEY=change-me-to-a-safe-secret-key
DEBUG=True
ALLOWED_HOSTS=*

# ApotekApps API base URL (no trailing slash)
APOTEK_API_BASE_URL=http://127.0.0.1:8000/api

# Credentials used to obtain an ApotekApps token for monitoring
APOTEK_ADMIN_USERNAME=admin
APOTEK_ADMIN_PASSWORD=admin
```

---

## Default Login

| Field    | Value   |
|----------|---------|
| Username | `admin` |
| Password | `admin` |

Login at **http://127.0.0.1:8090/login/**

---

## Project Structure

```
ApotekMonitor/
├── apps/
│   ├── accounts/          # Login / logout
│   └── monitor/
│       ├── models.py      # APIEndpoint, APIRequestLog, WebhookEvent, Alert
│       ├── services.py    # HTTP client (JWT, retry, rate-limit)
│       ├── views.py       # Dashboard, logs, ping, stats, topology, network stream, webhook
│       ├── urls.py
│       └── management/commands/
│           ├── seed_endpoints.py     # Populate ApotekApps endpoints
│           ├── seed_fake.py          # Generate dummy data for demos
│           └── simulate_traffic.py   # Emit live traffic for the network stream
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
│   │   ├── topology.html
│   │   ├── webhooks.html
│   │   ├── alerts.html
│   │   └── deliveries.html
│   └── partials/
│       ├── sidebar.html
│       └── navbar.html
├── static/
│   ├── css/
│   │   ├── theme.css      # Neon dark theme (shared with ApotekApps)
│   │   └── main.css       # ApotekMonitor-specific components
│   └── js/main.js
├── manage.py
├── requirements.txt
├── run.sh
├── push.sh
└── .env.example
```

---

## Pages & URLs

| URL | Description |
|-----|-------------|
| `/` | Main dashboard |
| `/endpoints/` | All endpoints + ping |
| `/endpoints/<id>/` | Endpoint detail + log history |
| `/logs/` | All request logs (filter + pagination) |
| `/topology/` | Topology smartscape + live network stream |
| `/webhooks/` | Received webhook events |
| `/alerts/` | Alert / notification history |
| `/deliveries/` | Webhook delivery history |
| `/api/ping/<id>/` | Ping endpoint (JSON) |
| `/api/stats/` | Chart data (JSON) |
| `/api/activity/` | Recent activity for topology animation (JSON) |
| `/api/topology/` | Topology nodes & edges (JSON) |
| `/api/network/stream/` | **Live network stream (SSE)** |
| `/api/alerts/` | Alerts + unread count (JSON) |
| `/webhook/receive/` | Receive webhook events (POST) |
| `/login/` | Login page |
| `/admin/` | Django admin |

---

## Topology & Live Network Stream

The `/topology/` page renders the infrastructure smartscape. Node/edge data is polled every 3 seconds from `/api/topology/`.

Network data is streamed **live** via SSE at `/api/network/stream/`:

- **New API request** → a packet travels along edge `nginx → apps_api` then `apps_api → svc_<module>` (green = success, red = failed).
- **New webhook** → a packet travels along edge `apps_api → monitor` (purple).

The **Network Stream** side panel shows a summary (total packets, packets/sec, requests, webhooks) and a live event feed.

The server uses `StreamingHttpResponse` with `text/event-stream` — no extra dependencies. The connection auto-reconnects if it drops.

### Generate live traffic for the demo

To make the network stream active without real user actions, run the traffic simulator (leave it running in a separate terminal):

```bash
python manage.py simulate_traffic            # ~2 events/sec, runs until stopped
python manage.py simulate_traffic --rate 5   # 5 events/sec
python manage.py simulate_traffic --duration 120  # stop after 120 seconds
```

---

## Seed Data

Populate ApotekApps endpoints into the database:

```bash
python manage.py seed_endpoints
```

Generate dummy logs & webhooks (historical, for charts/dashboards):

```bash
python manage.py seed_fake
```

> Note: `seed_fake` creates *historical* records, so they will not appear in the live SSE stream. Use `simulate_traffic` for live stream activity.

---

## Webhook

Send an event from another system to ApotekMonitor:

```bash
curl -X POST http://127.0.0.1:8090/webhook/receive/ \
  -H "Content-Type: application/json" \
  -d '{"event": "stock_empty", "medicine": "Paracetamol", "qty": 0}'
```

The event is stored in `WebhookEvent` and shown on `/webhooks/`, and it also flows into the live network stream.

---

## Tech Stack

- **Backend** — Django 4.2, SQLite
- **HTTP Client** — requests + urllib3 Retry
- **Auth** — Django session (monitor) + auto-managed JWT (ApotekApps API)
- **Realtime** — Server-Sent Events (SSE) via `StreamingHttpResponse`
- **Frontend** — Django templates, Chart.js 4.4, Font Awesome 6.5, vanilla JS (SVG smartscape)
- **Icons** — Simple Icons brand SVGs (PostgreSQL/Redis/SQLite/Nginx) + Font Awesome
- **Theme** — Neon Dark (shared with ApotekApps)

---

## Push to GitHub

```bash
sh push.sh
```

> Remote: `https://github.com/harys-rifai/ApotekMonitor.git`
