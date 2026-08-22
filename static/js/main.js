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

// ── Sidebar toggle ────────────────────────────────────────────
const toggleBtn = document.getElementById("sidebarToggle");
const sidebar   = document.getElementById("sidebar");
const wrapper   = document.querySelector(".main-wrapper");
if (toggleBtn && sidebar) {
  toggleBtn.addEventListener("click", () => {
    sidebar.classList.toggle("open");
    // on desktop collapse by shifting wrapper
    if (window.innerWidth > 768) {
      const collapsed = sidebar.classList.toggle("sidebar--collapsed");
      if (wrapper) wrapper.style.marginLeft = collapsed ? "0" : "var(--sidebar-width)";
    }
  });
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

// ── Auto-dismiss Django messages ──────────────────────────────
document.querySelectorAll(".alert").forEach(el => {
  setTimeout(() => {
    el.style.transition = "opacity .4s";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 400);
  }, 4500);
});
