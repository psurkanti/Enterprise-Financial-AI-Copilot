/* Shared UI helpers used by Admin + Team copilot pages. */
(function initSharedCopilotUI(global) {
  function setAskButtonLoading(buttonId, loading, idleText) {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.disabled = Boolean(loading);
    btn.classList.toggle("sending", Boolean(loading));
    btn.textContent = loading ? "Analyzing..." : idleText;
  }

  function setLatency(metaId, ms) {
    const el = document.getElementById(metaId);
    if (!el) return;
    if (!Number.isFinite(ms)) {
      el.textContent = "Last response: —";
      return;
    }
    el.textContent = `Last response: ${(ms / 1000).toFixed(2)}s`;
  }

  function setConnectionStatus(badgeId, status, text) {
    const el = document.getElementById(badgeId);
    if (!el) return;
    el.classList.remove("status-ok", "status-warn", "status-error");
    if (status === "ok") el.classList.add("status-ok");
    else if (status === "warn") el.classList.add("status-warn");
    else el.classList.add("status-error");
    el.textContent = text || "API Connected";
  }

  function showToast(message, kind, timeoutMs) {
    const root = document.getElementById("toastRoot");
    if (!root) return;
    const toast = document.createElement("div");
    toast.className = `toast ${kind || "info"}`;
    toast.textContent = String(message || "");
    root.appendChild(toast);
    window.setTimeout(() => toast.remove(), Number(timeoutMs || 2600));
  }

  global.CopilotUI = {
    setAskButtonLoading,
    setLatency,
    setConnectionStatus,
    showToast,
  };
})(window);
