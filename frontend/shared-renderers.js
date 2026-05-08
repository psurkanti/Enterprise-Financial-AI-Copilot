/* Shared copilot inline renderers (table + chart). */
(function initSharedRenderers(global) {
  function buildInlineRecordsTable(records, maxHeightPx, exportFilename) {
    const root = document.createElement("div");
    root.className = "copilot-inline-table-card";
    if (!records || records.length === 0) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.textContent = "No matching rows for this answer.";
      root.appendChild(empty);
      return root;
    }
    const columns = Object.keys(records[0]);
    let sortCol = columns[0];
    let sortAsc = true;
    let page = 1;
    const pageSize = 8;

    const controls = document.createElement("div");
    controls.className = "inline-table-controls";
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "ghost-btn";
    copyBtn.textContent = "Copy Table";
    const exportBtn = document.createElement("button");
    exportBtn.type = "button";
    exportBtn.className = "ghost-btn";
    exportBtn.textContent = "Export CSV";
    controls.append(copyBtn, exportBtn);

    const wrap = document.createElement("div");
    wrap.className = "table-wrap copilot-inline-table";
    if (maxHeightPx) wrap.style.maxHeight = `${maxHeightPx}px`;
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const tbody = document.createElement("tbody");
    table.append(thead, tbody);
    wrap.appendChild(table);

    const pager = document.createElement("div");
    pager.className = "inline-table-pager";
    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "ghost-btn";
    prev.textContent = "Prev";
    const pageText = document.createElement("span");
    const next = document.createElement("button");
    next.type = "button";
    next.className = "ghost-btn";
    next.textContent = "Next";
    pager.append(prev, pageText, next);

    function getSorted() {
      return [...records].sort((a, b) => {
        const av = a?.[sortCol] ?? "";
        const bv = b?.[sortCol] ?? "";
        const an = Number(av);
        const bn = Number(bv);
        const cmp = Number.isFinite(an) && Number.isFinite(bn)
          ? an - bn
          : String(av).localeCompare(String(bv));
        return sortAsc ? cmp : -cmp;
      });
    }

    function render() {
      const sorted = getSorted();
      const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
      page = Math.min(page, totalPages);
      const start = (page - 1) * pageSize;
      const rows = sorted.slice(start, start + pageSize);

      thead.innerHTML = "";
      const hr = document.createElement("tr");
      columns.forEach((c) => {
        const th = document.createElement("th");
        th.className = "sortable-th";
        th.textContent = c + (c === sortCol ? (sortAsc ? " ▲" : " ▼") : "");
        th.addEventListener("click", () => {
          if (sortCol === c) sortAsc = !sortAsc;
          else {
            sortCol = c;
            sortAsc = true;
          }
          render();
        });
        hr.appendChild(th);
      });
      thead.appendChild(hr);

      tbody.innerHTML = "";
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        columns.forEach((c) => {
          const td = document.createElement("td");
          td.textContent = row[c] ?? "";
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });

      prev.disabled = page <= 1;
      next.disabled = page >= totalPages;
      pageText.textContent = `Page ${page} of ${totalPages}`;
    }

    prev.addEventListener("click", () => { page -= 1; render(); });
    next.addEventListener("click", () => { page += 1; render(); });
    copyBtn.addEventListener("click", async () => {
      const csv = [columns.join(","), ...records.map((r) => columns.map((c) => JSON.stringify(r[c] ?? "")).join(","))].join("\n");
      await navigator.clipboard.writeText(csv);
    });
    exportBtn.addEventListener("click", () => {
      const csv = [columns.join(","), ...records.map((r) => columns.map((c) => JSON.stringify(r[c] ?? "")).join(","))].join("\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = exportFilename || "copilot_records.csv";
      a.click();
      URL.revokeObjectURL(url);
    });

    root.append(controls, wrap, pager);
    render();
    return root;
  }

  function openChartModal(title, config) {
    const backdrop = document.createElement("div");
    backdrop.className = "chart-modal-backdrop";
    const modal = document.createElement("div");
    modal.className = "chart-modal";
    const header = document.createElement("div");
    header.className = "chart-modal-header";
    const h = document.createElement("h4");
    h.textContent = title;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "ghost-btn";
    close.textContent = "Close";
    header.append(h, close);
    const canvas = document.createElement("canvas");
    canvas.className = "chart-modal-canvas";
    modal.append(header, canvas);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    new Chart(canvas, config);
    function cleanup() {
      backdrop.remove();
    }
    close.addEventListener("click", cleanup);
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) cleanup();
    });
  }

  function buildInlineChart(chartData) {
    if (!chartData || typeof Chart === "undefined") return null;
    const labels = Array.isArray(chartData.labels) ? chartData.labels : [];
    const values = Array.isArray(chartData.values) ? chartData.values : [];
    if (!labels.length || !values.length || labels.length !== values.length) return null;

    const wrap = document.createElement("section");
    wrap.className = "copilot-inline-chart";
    const title = document.createElement("h4");
    title.textContent = chartData.title || "Chart";
    const expandBtn = document.createElement("button");
    expandBtn.type = "button";
    expandBtn.className = "ghost-btn chart-expand-btn";
    expandBtn.textContent = "Expand";
    const canvas = document.createElement("canvas");
    wrap.append(title, expandBtn, canvas);

    const kind = ["line", "bar", "doughnut", "pie", "radar"].includes(chartData.kind) ? chartData.kind : "bar";
    const config = {
      type: kind,
      data: {
        labels,
        datasets: [
          {
            label: chartData.title || "Value",
            data: values.map((v) => Number(v || 0)),
            backgroundColor: kind === "line" ? "rgba(59,130,246,0.22)" : "#3b82f6",
            borderColor: "#1d4ed8",
            borderWidth: 2,
            fill: kind === "line",
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: kind !== "bar" } },
      },
    };
    new Chart(canvas, config);
    expandBtn.addEventListener("click", () => openChartModal(chartData.title || "Chart", config));
    return wrap;
  }

  global.CopilotRenderers = {
    buildInlineRecordsTable,
    buildInlineChart,
    openChartModal,
  };
})(window);
