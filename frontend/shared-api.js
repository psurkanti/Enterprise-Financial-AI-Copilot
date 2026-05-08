/* Shared backend API fallback helper. */
(function initSharedApi(global) {
  async function fetchWithFallback(path, options, candidates, onBaseSelected) {
    let lastErr = null;
    for (const base of candidates || []) {
      try {
        const res = await fetch(`${base}${path}`, options || {});
        const raw = await res.text();
        let data = {};
        try {
          data = raw ? JSON.parse(raw) : {};
        } catch (_err) {
          data = { detail: raw.slice(0, 180) };
        }
        const looksLikeHtml = /^\s*</.test(raw || "");
        if (looksLikeHtml && !res.headers.get("content-type")?.includes("application/json")) {
          lastErr = new Error(`Non-JSON response from ${base}${path}`);
          continue;
        }
        if (typeof onBaseSelected === "function") onBaseSelected(base);
        return { ok: res.ok, status: res.status, data, base };
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error("Could not connect to backend API.");
  }

  global.CopilotApi = {
    fetchWithFallback,
  };
})(window);
