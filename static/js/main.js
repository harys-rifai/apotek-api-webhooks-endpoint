/* ApotekMonitor — main.js */

// ── Clock ─────────────────────────────────────────────────────
const clockEl = document.getElementById("clock");
if (clockEl) {
  const tick = () => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString("id-ID", {
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    });
  };
  tick();
  setInterval(tick, 1000);
}

// ── Toast helper ──────────────────────────────────────────────
window.showToast = function(msg, type = "success") {

  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<i class="fa-solid fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'circle-xmark' : 'triangle-exclamation'}"></i> ${msg}`;
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 400); }, 3500);
};

// ── Navbar notifications (bell + dropdown) ───────────────────
(function () {
  const bell = document.getElementById("bellBtn");
  const badge = document.getElementById("bellBadge");
  const panel = document.getElementById("notifyPanel");
  const list = document.getElementById("notifyList");
  const markAll = document.getElementById("markAllRead");
  if (!bell || !badge || !panel || !list) return;

  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(^|;)\\s*" + name + "=([^;]+)"));
    return m ? m[2] : "";
  }
  function timeAgo(iso) {
    const d = new Date(iso), s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 60) return s + " dtk lalu";
    if (s < 3600) return Math.floor(s / 60) + " mnt lalu";
    if (s < 86400) return Math.floor(s / 3600) + " jam lalu";
    return Math.floor(s / 86400) + " hr lalu";
  }
  function esc(s) {
    return (s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  let lastUnread = 0;
  async function loadAlerts() {
    try {
      const r = await fetch("/api/alerts/", { headers: { "X-Requested-With": "XMLHttpRequest" } });
      const d = await r.json();
      const n = d.unread || 0;
      badge.textContent = n > 99 ? "99+" : n;
      badge.style.display = n > 0 ? "block" : "none";
      if (n > lastUnread && lastUnread !== 0) {
        bell.classList.add("has-unread");
        setTimeout(() => bell.classList.remove("has-unread"), 1500);
      }
      lastUnread = n;

      if (!d.alerts.length) {
        list.innerHTML = '<div class="navbar__empty">Belum ada notifikasi</div>';
        return;
      }
      list.innerHTML = d.alerts.map(a => `
        <div class="navbar__item ${a.is_read ? "" : "unread"}" data-id="${a.id}">
          <div class="navbar__item-ic ${a.level}"><i class="fa-solid ${a.level === 'critical' ? 'fa-circle-xmark' : a.level === 'warning' ? 'fa-triangle-exclamation' : a.level === 'success' ? 'fa-circle-check' : 'fa-circle-info'}"></i></div>
          <div class="navbar__item-body">
            <div class="navbar__item-title">${esc(a.title)}</div>
            ${a.message ? `<div class="navbar__item-time">${esc(a.message)}</div>` : ""}
            <div class="navbar__item-time">${timeAgo(a.created_at)} · ${esc(a.source)}</div>
          </div>
        </div>`).join("");
    } catch (e) { /* ignore */ }
  }

  bell.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = panel.classList.toggle("open");
    if (open) loadAlerts();
  });
  document.addEventListener("click", (e) => {
    if (!panel.contains(e.target) && !bell.contains(e.target)) panel.classList.remove("open");
  });

  list.addEventListener("click", async (e) => {
    const item = e.target.closest(".navbar__item");
    if (!item) return;
    const id = item.dataset.id;
    item.classList.remove("unread");
    try {
      await fetch("/api/alert/mark-read/", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": getCookie("csrftoken") },
        body: JSON.stringify({ id }),
      });
      loadAlerts();
    } catch (_) {}
  });

  if (markAll) {
    markAll.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await fetch("/api/alert/mark-read/", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": getCookie("csrftoken") },
          body: JSON.stringify({}),
        });
        loadAlerts();
      } catch (_) {}
    });
  }

  loadAlerts();
  setInterval(loadAlerts, 15000);
})();
