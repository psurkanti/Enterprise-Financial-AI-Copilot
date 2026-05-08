/** Prefer same origin, but auto-fallback to known local API ports. */
const API_BASE_CANDIDATES = Array.from(
  new Set(
    [window.location.origin, "http://127.0.0.1:8844", "http://127.0.0.1:8000"].filter(
      (x) => x && x !== "null"
    )
  )
);
const ACTIVE_DATASET_KEY = "activeDatasetName";
const state = {
  apiBase: API_BASE_CANDIDATES[0],
  activeDataset: localStorage.getItem(ACTIVE_DATASET_KEY) || "None",
  pendingDatasetId: "",
  datasets: [],
  activeDatasetMeta: null,
  summary: null,
  records: [],
  sessionId: sessionStorage.getItem("copilotSessionId") || "",
  /** True after /summary returns 200 — backend may already have active_invoices.csv before this browser session. */
  hasActiveDataset: false,
  currentReportType: "aging",
  currentReportRows: [],
  lastQuestion: "",
  dashboardFilters: {
    status: "all",
    topNRegions: 8,
  },
  dashboardDrilldown: {
    type: "",
    value: "",
  },
  charts: {
    outstanding: null,
    overdue: null,
    riskByRegion: null,
    agingBucket: null,
  },
};

function setActivateButtonEnabled(enabled) {
  const btn = document.getElementById("activatePreviewBtn");
  if (!btn) return;
  btn.disabled = !enabled;
}

async function apiFetch(path, options = {}) {
  return window.CopilotApi.fetchWithFallback(path, options, API_BASE_CANDIDATES, (base) => {
    state.apiBase = base;
  });
}

function currency(v) {
  return `$${Number(v || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatDate(value) {
  if (!value) return "-";
  return String(value).slice(0, 10);
}

function statusBadge(status) {
  const value = String(status || "").toLowerCase();
  if (value === "paid") return '<span class="badge green">Paid</span>';
  if (value === "pending") return '<span class="badge yellow">Pending</span>';
  return '<span class="badge red">Overdue</span>';
}

function riskBadge(score) {
  const n = Number(score || 0);
  if (n >= 70) return '<span class="badge red">High</span>';
  if (n >= 40) return '<span class="badge yellow">Medium</span>';
  return '<span class="badge green">Low</span>';
}

function setCopilotInsightPlaceholders() {}

function setDashboardLoading(loading) {
  const shell = document.getElementById("appShell");
  if (!shell) return;
  shell.classList.toggle("loading", Boolean(loading));
  shell.setAttribute("aria-busy", loading ? "true" : "false");
}

function clearKpiPlaceholders() {
  document.getElementById("kpiTotalDue").textContent = "-";
  document.getElementById("kpiTotalInvoices").textContent = "-";
  document.getElementById("kpiOverdueInvoices").textContent = "-";
  document.getElementById("kpiHighRisk").textContent = "-";
  document.getElementById("kpiTopRegion").textContent = "-";
}

async function fetchSummary() {
  try {
    setDashboardLoading(true);
    const { ok, data } = await apiFetch("/summary", { cache: "no-store" });
    if (!ok) {
      state.hasActiveDataset = false;
      state.summary = null;
      clearKpiPlaceholders();
      document.getElementById("activeDatasetName").textContent = state.activeDataset || "None";
      document.getElementById("dataStatusText").textContent =
        typeof data.detail === "string"
          ? data.detail
          : "No active dataset on the server. An admin must upload a CSV first.";
      return;
    }
    state.hasActiveDataset = true;
    state.summary = data;
    if (!state.activeDataset || state.activeDataset === "None") {
      state.activeDataset = "active_invoices.csv";
    }
    localStorage.setItem(ACTIVE_DATASET_KEY, state.activeDataset);
    document.getElementById("activeDatasetName").textContent = state.activeDataset;
    document.getElementById("kpiTotalDue").textContent = currency(data.total_due);
    document.getElementById("kpiTotalInvoices").textContent = data.total_invoices;
    document.getElementById("kpiOverdueInvoices").textContent = data.overdue_invoices;
    document.getElementById("kpiHighRisk").textContent = data.high_risk_customers;
    document.getElementById("kpiTopRegion").textContent = data.top_region_by_balance;
    document.getElementById("dataStatusText").textContent = `Active dataset: ${state.activeDataset} | ${data.total_invoices} records loaded`;
  } catch (err) {
    state.hasActiveDataset = false;
    state.summary = null;
    document.getElementById("activeDatasetName").textContent = state.activeDataset || "None";
    clearKpiPlaceholders();
    document.getElementById("dataStatusText").textContent =
      `Could not refresh server data right now (${String(err)}). Last known dataset: ${state.activeDataset || "None"}.`;
  } finally {
    setDashboardLoading(false);
  }
}

async function fetchInvoices(limit = 200) {
  if (!state.hasActiveDataset) {
    state.records = [];
    renderRecentTable([]);
    renderPreviewTable([]);
    renderDashboardCharts([]);
    return;
  }
  try {
    setDashboardLoading(true);
    const { ok, data } = await apiFetch(`/invoices?limit=${limit}`, { cache: "no-store" });
    if (!ok) {
      state.records = [];
      renderRecentTable([]);
      renderPreviewTable([]);
      renderDashboardCharts([]);
      document.getElementById("dataStatusText").textContent =
        typeof data.detail === "string" ? data.detail : "Failed to load invoice rows.";
      return;
    }
    state.records = data.records || [];
    renderRecentTable(state.records);
    renderPreviewTable(state.records.slice(0, 10));
    renderDashboardCharts(state.records);
  } catch (err) {
    state.records = [];
    renderRecentTable([]);
    renderPreviewTable([]);
    renderDashboardCharts([]);
    document.getElementById("dataStatusText").textContent = String(err);
  } finally {
    setDashboardLoading(false);
  }
}

function destroyChart(chart) {
  if (chart && typeof chart.destroy === "function") chart.destroy();
}

function getDashboardBaseRecords() {
  const statusFilter = state.dashboardFilters?.status || "all";
  if (statusFilter === "all") return state.records || [];
  return (state.records || []).filter((r) => String(r.status || "").toLowerCase() === statusFilter);
}

function getDashboardDrilldownRecords() {
  const base = getDashboardBaseRecords();
  const type = state.dashboardDrilldown?.type || "";
  const value = state.dashboardDrilldown?.value || "";
  if (!type || !value) return base;
  if (type === "region" || type === "risk_region") {
    return base.filter((r) => String(r.region || "Unknown") === value);
  }
  if (type === "aging_bucket") {
    return base.filter((r) => String(r.aging_bucket || "Unknown") === value);
  }
  if (type === "overdue_share") {
    return base.filter((r) => {
      const status = String(r.status || "").toLowerCase();
      return value === "Overdue" ? status === "overdue" : status !== "overdue";
    });
  }
  return base;
}

function renderDashboardTableFromState() {
  const rows = getDashboardDrilldownRecords();
  renderRecentTable(rows);
  const drillLabel = state.dashboardDrilldown?.type
    ? ` | Drilldown: ${state.dashboardDrilldown.type} = ${state.dashboardDrilldown.value}`
    : "";
  document.getElementById("dataStatusText").textContent =
    `Active dataset: ${state.activeDataset} | ${rows.length} records in view${drillLabel}`;
}

function setDashboardDrilldown(type, value) {
  state.dashboardDrilldown = { type: String(type || ""), value: String(value || "") };
  renderDashboardTableFromState();
}

function toggleDashboardDrilldown(type, value) {
  const currentType = state.dashboardDrilldown?.type || "";
  const currentValue = state.dashboardDrilldown?.value || "";
  if (currentType === type && currentValue === value) {
    state.dashboardDrilldown = { type: "", value: "" };
  } else {
    state.dashboardDrilldown = { type: String(type || ""), value: String(value || "") };
  }
  renderDashboardCharts(state.records || []);
}

function renderDashboardCharts(records) {
  const hasChartLib = typeof Chart !== "undefined";
  if (!hasChartLib) return;
  const statusFilter = state.dashboardFilters?.status || "all";
  const topNRegions = Number(state.dashboardFilters?.topNRegions || 8);
  const filteredRecords = statusFilter === "all"
    ? records
    : records.filter((r) => String(r.status || "").toLowerCase() === statusFilter);

  const outstandingMap = {};
  const riskMap = {};
  const agingMap = {};
  const statusCounts = { paid: 0, pending: 0, overdue: 0 };
  let totalOutstanding = 0;
  let overdueCount = 0;

  filteredRecords.forEach((row) => {
    const amount = Number(row.invoice_amount_due || 0);
    const region = row.region || "Unknown";
    const status = String(row.status || "").toLowerCase();
    const aging = row.aging_bucket || "Unknown";
    const risk = Number(row.risk_score || 0);

    outstandingMap[region] = (outstandingMap[region] || 0) + amount;
    riskMap[region] = riskMap[region] || { totalRisk: 0, count: 0 };
    riskMap[region].totalRisk += risk;
    riskMap[region].count += 1;
    agingMap[aging] = (agingMap[aging] || 0) + amount;
    totalOutstanding += amount;

    if (status in statusCounts) statusCounts[status] += 1;
    else statusCounts.overdue += 1;
    if (status === "overdue") overdueCount += 1;
  });

  const overduePct = filteredRecords.length ? (overdueCount / filteredRecords.length) * 100 : 0;

  const outstandingEntries = Object.entries(outstandingMap)
    .sort((a, b) => b[1] - a[1])
    .slice(0, topNRegions);
  const riskEntries = Object.entries(riskMap)
    .map(([region, stat]) => [region, stat.count ? stat.totalRisk / stat.count : 0])
    .sort((a, b) => b[1] - a[1]);
  const agingEntries = Object.entries(agingMap).sort((a, b) => b[1] - a[1]);
  const focusedRegion = ["region", "risk_region"].includes(state.dashboardDrilldown?.type)
    ? state.dashboardDrilldown?.value
    : "";

  const outstandingCtx = document.getElementById("outstandingChart");
  const overdueCtx = document.getElementById("overdueChart");
  const riskCtx = document.getElementById("riskRegionChart");
  const agingCtx = document.getElementById("agingBucketChart");
  const insight = document.getElementById("dashboardInsightText");
  if (!outstandingCtx || !overdueCtx || !riskCtx || !agingCtx) return;

  destroyChart(state.charts.outstanding);
  const outstandingLabels = outstandingEntries.map(([label]) => label);
  const outstandingValues = outstandingEntries.map(([, v]) => Number(v.toFixed(2)));
  const outstandingColors = outstandingLabels.map((label) => {
    if (!focusedRegion) return "#3b82f6";
    return label === focusedRegion ? "#1d4ed8" : "rgba(147, 197, 253, 0.45)";
  });
  state.charts.outstanding = new Chart(outstandingCtx, {
    type: "bar",
    data: {
      labels: outstandingLabels,
      datasets: [{ label: "Outstanding", data: outstandingValues, backgroundColor: outstandingColors, borderRadius: 8 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: "easeOutQuart" },
      onClick: (_event, elements, chart) => {
        if (!elements?.length) return;
        const idx = elements[0].index;
        const region = chart?.data?.labels?.[idx];
        if (!region) return;
        toggleDashboardDrilldown("region", region);
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: ${currency(ctx.raw)}`,
          },
        },
      },
    },
  });

  destroyChart(state.charts.overdue);
  state.charts.overdue = new Chart(overdueCtx, {
    type: "doughnut",
    data: {
      labels: ["Overdue", "Non-Overdue"],
      datasets: [{ data: [Number(overduePct.toFixed(2)), Number((100 - overduePct).toFixed(2))], backgroundColor: ["#ef4444", "#93c5fd"] }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: "easeOutQuart" },
      onClick: (_event, elements, chart) => {
        if (!elements?.length) return;
        const idx = elements[0].index;
        const label = chart?.data?.labels?.[idx];
        if (!label) return;
        toggleDashboardDrilldown("overdue_share", label);
      },
      plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${ctx.raw}%` } } },
    },
  });

  destroyChart(state.charts.riskByRegion);
  const riskLabels = riskEntries.map(([label]) => label);
  const riskValues = riskEntries.map(([, v]) => Number(v.toFixed(1)));
  const riskPointBg = riskLabels.map((label) => {
    if (!focusedRegion) return "#1d4ed8";
    return label === focusedRegion ? "#1e40af" : "rgba(147, 197, 253, 0.7)";
  });
  const riskPointRadius = riskLabels.map((label) => (focusedRegion && label === focusedRegion ? 5 : 3));
  state.charts.riskByRegion = new Chart(riskCtx, {
    type: "radar",
    data: {
      labels: riskLabels,
      datasets: [{
        label: "Avg Risk Score",
        data: riskValues,
        borderColor: "#1d4ed8",
        backgroundColor: "rgba(37, 99, 235, 0.25)",
        pointBackgroundColor: riskPointBg,
        pointRadius: riskPointRadius,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: "easeOutQuart" },
      onClick: (_event, elements, chart) => {
        if (!elements?.length) return;
        const idx = elements[0].index;
        const region = chart?.data?.labels?.[idx];
        if (!region) return;
        toggleDashboardDrilldown("risk_region", region);
      },
      scales: { r: { suggestedMin: 0, suggestedMax: 100 } },
    },
  });

  destroyChart(state.charts.agingBucket);
  state.charts.agingBucket = new Chart(agingCtx, {
    type: "line",
    data: {
      labels: agingEntries.map(([label]) => label),
      datasets: [{ label: "Amount Due", data: agingEntries.map(([, v]) => Number(v.toFixed(2))), borderColor: "#0ea5e9", backgroundColor: "rgba(14,165,233,0.2)", fill: true, tension: 0.3 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: "easeOutQuart" },
      onClick: (_event, elements, chart) => {
        if (!elements?.length) return;
        const idx = elements[0].index;
        const bucket = chart?.data?.labels?.[idx];
        if (!bucket) return;
        toggleDashboardDrilldown("aging_bucket", bucket);
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${currency(ctx.raw)}`,
          },
        },
      },
    },
  });

  const topRegion = outstandingEntries[0]?.[0] || "N/A";
  const totalAmountLabel = currency(totalOutstanding);
  if (insight) {
    const drill = state.dashboardDrilldown?.type
      ? ` Drilldown active on ${state.dashboardDrilldown.type}: ${state.dashboardDrilldown.value}.`
      : "";
    insight.textContent = `Showing ${filteredRecords.length} records (${statusFilter}). Total outstanding: ${totalAmountLabel}. Top region: ${topRegion}.${drill}`;
  }
  renderDashboardTableFromState();
}

function renderRecentTable(records) {
  const tbody = document.querySelector("#recentTable tbody");
  tbody.innerHTML = "";
  records
    .slice()
    .sort((a, b) => String(b.due_date).localeCompare(String(a.due_date)))
    .slice(0, 12)
    .forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row.customer_name || "-"}</td>
        <td>${row.invoice_id || "-"}</td>
        <td>${currency(row.invoice_amount_due)}</td>
        <td>${formatDate(row.due_date)}</td>
        <td>${statusBadge(row.status)}</td>
        <td>${row.region || "-"}</td>
        <td>${riskBadge(row.risk_score)} (${Number(row.risk_score || 0)})</td>
      `;
      tbody.appendChild(tr);
    });
}

function applyDashboardSearch() {
  const query = (document.getElementById("searchInput").value || "").trim().toLowerCase();
  if (!state.hasActiveDataset) {
    document.getElementById("dataStatusText").textContent =
      "No active dataset on the server. An admin must upload a CSV first.";
    renderRecentTable([]);
    return;
  }

  if (!query) {
    renderDashboardTableFromState();
    return;
  }

  const matches = getDashboardDrilldownRecords().filter((row) => {
    const customer = String(row.customer_name || "").toLowerCase();
    const invoice = String(row.invoice_id || "").toLowerCase();
    const region = String(row.region || "").toLowerCase();
    return customer.includes(query) || invoice.includes(query) || region.includes(query);
  });
  renderRecentTable(matches);
  if (matches.length === 0) {
    document.getElementById("dataStatusText").textContent = `No records found for "${query}".`;
  } else {
    document.getElementById("dataStatusText").textContent = `Found ${matches.length} matching records for "${query}".`;
  }
}

function renderPreviewTable(records) {
  const table = document.getElementById("previewTable");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";
  if (!records.length) return;
  const columns = Object.keys(records[0]);
  const hr = document.createElement("tr");
  columns.forEach((c) => {
    const th = document.createElement("th");
    th.textContent = c;
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  records.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((c) => {
      const td = document.createElement("td");
      td.textContent = row[c] ?? "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderDatasetHistory(datasets) {
  const tbody = document.querySelector("#datasetHistoryTable tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  datasets.forEach((ds) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${ds.dataset_name || "-"}</td>
      <td>${(ds.uploaded_at || "").replace("T", " ").slice(0, 19)}</td>
      <td>${ds.uploaded_by || "-"}</td>
      <td>${Number(ds.rows || 0)}</td>
      <td>${ds.is_active ? "Yes" : "No"}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderDatasetSelector(datasets, activeId) {
  const sel = document.getElementById("activeDatasetSelector");
  if (!sel) return;
  sel.innerHTML = "";
  datasets.forEach((ds) => {
    const opt = document.createElement("option");
    opt.value = ds.dataset_id;
    opt.textContent = `${ds.dataset_name} (${ds.rows} rows)`;
    if (ds.dataset_id === activeId) opt.selected = true;
    sel.appendChild(opt);
  });
}

function renderActiveDatasetCard(dataset) {
  const nameEl = document.getElementById("activeDatasetName");
  const rowsEl = document.getElementById("activeDatasetRows");
  const atEl = document.getElementById("activeDatasetUploadedAt");
  const byEl = document.getElementById("activeDatasetUploadedBy");
  const statusEl = document.getElementById("activeDatasetStatusBadge");
  if (!nameEl || !rowsEl || !atEl || !byEl || !statusEl) return;
  if (!dataset) {
    nameEl.textContent = "None";
    rowsEl.textContent = "0";
    atEl.textContent = "-";
    byEl.textContent = "-";
    statusEl.textContent = "Inactive";
    statusEl.classList.remove("status-active");
    statusEl.classList.add("status-inactive");
    return;
  }
  nameEl.textContent = dataset.dataset_name || "Unknown";
  rowsEl.textContent = String(Number(dataset.rows || 0));
  atEl.textContent = String(dataset.uploaded_at || "").replace("T", " ").slice(0, 19) || "-";
  byEl.textContent = dataset.uploaded_by || "-";
  const isActive = Boolean(dataset.is_active);
  statusEl.textContent = isActive ? "Active" : "Inactive";
  statusEl.classList.toggle("status-active", isActive);
  statusEl.classList.toggle("status-inactive", !isActive);
}

async function refreshDatasets() {
  const { ok, data } = await apiFetch("/datasets", { cache: "no-store" });
  if (!ok) throw new Error(data.detail || "Could not load dataset history.");
  state.datasets = data.datasets || [];
  const active = state.datasets.find((d) => d.dataset_id === data.active_dataset_id) || state.datasets.find((d) => d.is_active);
  if (active) {
    state.activeDatasetMeta = active;
    state.activeDataset = active.dataset_name || "active";
    localStorage.setItem(ACTIVE_DATASET_KEY, state.activeDataset);
    document.getElementById("activeDatasetName").textContent = state.activeDataset;
  }
  renderActiveDatasetCard(active || null);
  renderDatasetHistory(state.datasets);
  renderDatasetSelector(state.datasets, data.active_dataset_id);
}

function renderRecords(records) {
  const table = document.getElementById("recordsTable");
  if (!table) return;
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";
  if (!records || records.length === 0) return;

  const columns = Object.keys(records[0]);
  const headerRow = document.createElement("tr");
  columns.forEach((c) => {
    const th = document.createElement("th");
    th.textContent = c;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  records.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((c) => {
      const td = document.createElement("td");
      td.textContent = row[c] ?? "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function toCsv(rows) {
  if (!rows || rows.length === 0) return "";
  const columns = Object.keys(rows[0]);
  const escape = (value) => {
    const text = String(value ?? "");
    if (text.includes(",") || text.includes('"') || text.includes("\n")) {
      return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
  };
  const header = columns.join(",");
  const body = rows.map((row) => columns.map((c) => escape(row[c])).join(",")).join("\n");
  return `${header}\n${body}`;
}

function downloadCsv(filename, rows) {
  const csv = toCsv(rows);
  if (!csv) return;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function renderReportTable(title, rows) {
  document.getElementById("reportTitle").textContent = title;
  const table = document.getElementById("reportTable");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";
  state.currentReportRows = rows;
  if (!rows || rows.length === 0) return;

  const columns = Object.keys(rows[0]);
  const hr = document.createElement("tr");
  columns.forEach((c) => {
    const th = document.createElement("th");
    th.textContent = c;
    hr.appendChild(th);
  });
  thead.appendChild(hr);

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((c) => {
      const td = document.createElement("td");
      td.textContent = row[c] ?? "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function renderReportSummaryStrip(rows) {
  const strip = document.getElementById("reportSummaryStrip");
  strip.className = "kpi-grid compact";
  strip.innerHTML = "";

  const recordCount = rows.length;
  const amountColumns = ["total_due", "amount_due", "invoice_amount_due"];
  let amountSum = 0;
  rows.forEach((row) => {
    const col = amountColumns.find((c) => row[c] !== undefined);
    if (col) amountSum += Number(row[col] || 0);
  });
  const average = recordCount > 0 ? amountSum / recordCount : 0;
  const reportType = state.currentReportType;

  let cards = [
    { label: "Rows in Report", value: String(recordCount) },
    { label: "Total Amount", value: currency(amountSum) },
    { label: "Average Amount", value: currency(average) },
  ];

  if (reportType === "region" && rows.length) {
    const top = rows.slice().sort((a, b) => Number(b.total_due || 0) - Number(a.total_due || 0))[0];
    cards = [
      { label: "Regions", value: String(rows.length) },
      { label: "Top Region", value: top.region || "-" },
      { label: "Top Region Due", value: currency(top.total_due || 0) },
    ];
  } else if (reportType === "overdue" && rows.length) {
    const highRisk = rows.filter((r) => Number(r.risk_score || 0) >= 70).length;
    const highRiskShare = rows.length ? `${Math.round((highRisk / rows.length) * 100)}%` : "0%";
    cards = [
      { label: "Overdue Invoices", value: String(rows.length) },
      { label: "Overdue Amount", value: currency(amountSum) },
      { label: "High-Risk Share", value: highRiskShare },
    ];
  } else if (reportType === "highrisk" && rows.length) {
    const topCustomer = rows[0]?.customer_name || "-";
    cards = [
      { label: "High-Risk Invoices", value: String(rows.length) },
      { label: "High-Risk Amount", value: currency(amountSum) },
      { label: "Top High-Risk Customer", value: topCustomer },
    ];
  } else if (reportType === "aging" && rows.length) {
    const topBucket = rows.slice().sort((a, b) => Number(b.total_due || 0) - Number(a.total_due || 0))[0];
    cards = [
      { label: "Aging Buckets", value: String(rows.length) },
      { label: "Top Aging Bucket", value: topBucket.aging_bucket || "-" },
      { label: "Top Bucket Due", value: currency(topBucket.total_due || 0) },
    ];
  }

  cards.forEach((card) => {
    const div = document.createElement("div");
    div.className = "kpi-card compact";
    div.innerHTML = `<span>${card.label}</span><strong>${card.value}</strong>`;
    strip.appendChild(div);
  });
}

function buildReportRows(reportType) {
  const rows = state.records || [];
  if (!rows.length) return [];

  if (reportType === "aging") {
    const map = {};
    rows.forEach((r) => {
      const key = r.aging_bucket || "Unknown";
      map[key] = (map[key] || 0) + Number(r.invoice_amount_due || 0);
    });
    return Object.entries(map).map(([aging_bucket, total_due]) => ({
      aging_bucket,
      total_due: Number(total_due.toFixed(2)),
    }));
  }

  if (reportType === "overdue") {
    return rows
      .filter((r) => String(r.status || "").toLowerCase() === "overdue")
      .sort((a, b) => Number(b.invoice_amount_due || 0) - Number(a.invoice_amount_due || 0))
      .map((r) => ({
        customer_name: r.customer_name,
        invoice_id: r.invoice_id || "-",
        amount_due: Number(r.invoice_amount_due || 0),
        due_date: formatDate(r.due_date),
        region: r.region,
        risk_score: r.risk_score,
      }));
  }

  if (reportType === "highrisk") {
    return rows
      .filter((r) => Number(r.risk_score || 0) >= 70)
      .sort((a, b) => Number(b.invoice_amount_due || 0) - Number(a.invoice_amount_due || 0))
      .map((r) => ({
        customer_name: r.customer_name,
        invoice_id: r.invoice_id || "-",
        amount_due: Number(r.invoice_amount_due || 0),
        risk_score: Number(r.risk_score || 0),
        status: r.status,
        region: r.region,
      }));
  }

  if (reportType === "region") {
    const map = {};
    rows.forEach((r) => {
      const key = r.region || "Unknown";
      map[key] = (map[key] || 0) + Number(r.invoice_amount_due || 0);
    });
    return Object.entries(map)
      .map(([region, total_due]) => ({ region, total_due: Number(total_due.toFixed(2)) }))
      .sort((a, b) => b.total_due - a.total_due);
  }

  return [];
}

function renderCurrentReport() {
  if (!state.hasActiveDataset) {
    renderReportTable("Reports", []);
    renderReportSummaryStrip([]);
    return;
  }
  const reportMap = {
    aging: "AR Aging Report",
    overdue: "Overdue Customers Report",
    highrisk: "High Risk Customers Report",
    region: "Region Outstanding Report",
  };
  const title = reportMap[state.currentReportType] || "Report";
  const rows = buildReportRows(state.currentReportType);
  renderReportTable(title, rows);
  renderReportSummaryStrip(rows);
}

function appendStructuredCopilotMessage(data) {
  const chat = document.getElementById("chatHistory");
  window.CopilotChat?.clearEmptyState("chatHistory");
  const style = data.response_style || "direct";
  const records = data.matching_records || [];

  if (typeof data.summary === "string") {
    data.summary = window.CopilotText?.sanitizeSummaryText(data.summary) ?? String(data.summary).trim();
  }

  if (style === "direct") {
    const row = document.createElement("div");
    row.className = "chat-message-row bot chat-enter";
    const avatar = document.createElement("span");
    avatar.className = "copilot-avatar small";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "✦";
    const div = document.createElement("div");
    div.className = "chat-bubble bot";
    const summaryText = data.summary || "—";
    const mdTable = window.CopilotText?.parseMarkdownTable(summaryText) ?? null;
    if (mdTable) {
      div.textContent = summaryText.split("\n").find((line) => !line.includes("|")) || "Here is the requested table:";
      const stack = document.createElement("div");
      stack.className = "chat-enter";
      stack.appendChild(div);
      stack.appendChild(window.CopilotText?.renderMarkdownTable(mdTable));
      const chart = window.CopilotRenderers?.buildInlineChart(data.chart_data);
      if (chart) stack.appendChild(chart);
      row.append(avatar, stack);
    } else {
      div.textContent = summaryText;
      const stack = document.createElement("div");
      stack.className = "chat-enter";
      stack.appendChild(div);
      const chart = window.CopilotRenderers?.buildInlineChart(data.chart_data);
      if (chart) stack.appendChild(chart);
      row.append(avatar, stack);
    }
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  if (style === "analytical") {
    const block = document.createElement("article");
    block.className = "copilot-answer-block chat-enter";
    const head = document.createElement("div");
    head.className = "copilot-answer-head";
    const avatar = document.createElement("span");
    avatar.className = "copilot-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "✦";
    const label = document.createElement("span");
    label.className = "copilot-answer-label";
    label.textContent = "Enterprise Financial AI Copilot";
    head.append(avatar, label);
    block.appendChild(head);

    const secSummary = document.createElement("section");
    secSummary.className = "copilot-answer-section";
    const hSum = document.createElement("h4");
    hSum.textContent = "Summary";
    const pSum = document.createElement("p");
    pSum.className = "copilot-summary-text";
    pSum.textContent = data.summary || "—";
    secSummary.append(hSum, pSum);
    block.appendChild(secSummary);

    const findings = data.key_findings || [];
    if (findings.length) {
      const secFind = document.createElement("section");
      secFind.className = "copilot-answer-section";
      const hF = document.createElement("h4");
      hF.textContent = "Key Findings";
      const ul = document.createElement("ul");
      ul.className = "copilot-findings";
      findings.forEach((f) => {
        const li = document.createElement("li");
        li.textContent = f;
        ul.appendChild(li);
      });
      secFind.append(hF, ul);
      block.appendChild(secFind);
    }

    const rec = (data.recommended_action || "").trim();
    if (rec) {
      const secAct = document.createElement("section");
      secAct.className = "copilot-answer-section";
      const hA = document.createElement("h4");
      hA.textContent = "Recommended Action";
      const pA = document.createElement("p");
      pA.className = "copilot-recommended";
      pA.textContent = rec;
      secAct.append(hA, pA);
      block.appendChild(secAct);
    }
    const chart = window.CopilotRenderers?.buildInlineChart(data.chart_data);
    if (chart) block.appendChild(chart);

    chat.appendChild(block);
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  if (style === "records" && records.length === 0) {
    const row = document.createElement("div");
    row.className = "chat-message-row bot chat-enter";
    const avatar = document.createElement("span");
    avatar.className = "copilot-avatar small";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "✦";
    const div = document.createElement("div");
    div.className = "chat-bubble bot";
    div.textContent = data.summary || "—";
    row.append(avatar, div);
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  const block = document.createElement("article");
  block.className = "copilot-answer-block chat-enter";

  const head = document.createElement("div");
  head.className = "copilot-answer-head";
  const avatar = document.createElement("span");
  avatar.className = "copilot-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "✦";
  const label = document.createElement("span");
  label.className = "copilot-answer-label";
  label.textContent = "Enterprise Financial AI Copilot";
  head.append(avatar, label);
  block.appendChild(head);

  const secSummary = document.createElement("section");
  secSummary.className = "copilot-answer-section";
  const hSum = document.createElement("h4");
  hSum.textContent = "Summary";
  const pSum = document.createElement("p");
  pSum.className = "copilot-summary-text";
  pSum.textContent = data.summary || "—";
  secSummary.append(hSum, pSum);
  block.appendChild(secSummary);

  const findings = data.key_findings || [];
  if (findings.length) {
    const secFind = document.createElement("section");
    secFind.className = "copilot-answer-section";
    const hF = document.createElement("h4");
    hF.textContent = "Key Findings";
    const ul = document.createElement("ul");
    ul.className = "copilot-findings";
    findings.forEach((f) => {
      const li = document.createElement("li");
      li.textContent = f;
      ul.appendChild(li);
    });
    secFind.append(hF, ul);
    block.appendChild(secFind);
  }

  if (records.length > 0) {
    const secTbl = document.createElement("section");
    secTbl.className = "copilot-answer-section";
    const hT = document.createElement("h4");
    hT.textContent = "Matching Records";
    secTbl.appendChild(hT);
    secTbl.appendChild(window.CopilotRenderers?.buildInlineRecordsTable(records, 240));
    block.appendChild(secTbl);
  }
  const chart = window.CopilotRenderers?.buildInlineChart(data.chart_data);
  if (chart) block.appendChild(chart);

  const secAct = document.createElement("section");
  secAct.className = "copilot-answer-section";
  const hA = document.createElement("h4");
  hA.textContent = "Recommended Action";
  const pA = document.createElement("p");
  pA.className = "copilot-recommended";
  const rec = (data.recommended_action || "").trim();
  pA.textContent = rec || "—";
  secAct.append(hA, pA);
  if (rec) {
    block.appendChild(secAct);
  }

  chat.appendChild(block);
  chat.scrollTop = chat.scrollHeight;
}

async function askQuestion(question) {
  state.lastQuestion = question;
  window.CopilotUI?.setAskButtonLoading("askBtn", true, "Ask Copilot");
  window.CopilotUI?.setConnectionStatus("copilotConnectionBadge", "warn", "Reconnecting...");
  const startedAt = performance.now();
  window.CopilotChat?.appendBubble("chatHistory", "user", question);
  const typing = window.CopilotChat?.showTyping("chatHistory");
  try {
    const { ok, data } = await apiFetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: state.sessionId || null }),
    });
    typing.remove();
    if (!ok) throw new Error(data.detail || "Ask failed");
    if (data.session_id) {
      state.sessionId = data.session_id;
      sessionStorage.setItem("copilotSessionId", state.sessionId);
    }
    window.CopilotUI?.setConnectionStatus("copilotConnectionBadge", "ok", "API Connected");
    appendStructuredCopilotMessage(data);
  } catch (err) {
    typing.remove();
    window.CopilotUI?.setConnectionStatus("copilotConnectionBadge", "error", "API Issue");
    appendChatErrorWithRetry(String(err), state.lastQuestion);
    window.CopilotUI?.showToast("Copilot request failed. You can retry.", "error");
  } finally {
    window.CopilotUI?.setAskButtonLoading("askBtn", false, "Ask Copilot");
    window.CopilotUI?.setLatency("copilotLatencyMeta", performance.now() - startedAt);
  }
}

async function uploadCsv() {
  const msg = document.getElementById("uploadMsg");
  const fileInput = document.getElementById("csvFile");
  if (!fileInput.files || fileInput.files.length === 0) {
    msg.textContent = "Please select a CSV/XLSX file.";
    return;
  }
  const uploadedBy = (document.getElementById("uploadedBy")?.value || "admin").trim() || "admin";
  const form = new FormData();
  form.append("file", fileInput.files[0]);
  form.append("uploaded_by", uploadedBy);
  const { ok, data } = await apiFetch("/datasets/preview", { method: "POST", body: form });
  if (!ok) throw new Error(data.detail || "Preview failed");
  state.pendingDatasetId = data?.dataset?.dataset_id || "";
  setActivateButtonEnabled(Boolean(state.pendingDatasetId));
  renderPreviewTable(data.preview_rows || []);
  const uploaded = data?.dataset?.rows != null ? ` (${data.dataset.rows} rows)` : "";
  document.getElementById("uploadMsg").textContent =
    `${data.message || "Preview ready"}${uploaded}. Click "Activate Previewed Dataset" to switch.`;
  window.CopilotUI?.showToast("Dataset preview loaded.", "success");
  await refreshDatasets();
}

async function activateDataset(datasetId) {
  if (!datasetId) return;
  const form = new FormData();
  form.append("dataset_id", datasetId);
  const { ok, data } = await apiFetch("/datasets/activate", { method: "POST", body: form });
  if (!ok) throw new Error(data.detail || "Activation failed");
  state.sessionId = "";
  sessionStorage.removeItem("copilotSessionId");
  state.pendingDatasetId = "";
  setActivateButtonEnabled(false);
  document.getElementById("uploadMsg").textContent = data.message || "Active dataset updated.";
  window.CopilotUI?.showToast("Active dataset updated.", "success");
  await refreshDatasets();
  await refreshAll();
}

function switchPage(pageId) {
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  document.getElementById(pageId).classList.add("active");
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
  document.querySelector(`[data-page="${pageId}"]`).classList.add("active");
  const pageTitle = {
    dashboardPage: "Admin Dashboard",
    uploadPage: "Admin Upload Data",
    copilotPage: "Financial Copilot",
    reportsPage: "Reports",
  }[pageId];
  const subtitle = {
    dashboardPage: "",
    uploadPage: "",
    copilotPage: "",
    reportsPage: "",
  }[pageId];
  document.getElementById("pageTitle").textContent = pageTitle;
  document.getElementById("pageSubtitle").textContent = subtitle;

  const searchInput = document.getElementById("searchInput");
  const showTopSearch = pageId === "dashboardPage";
  searchInput.style.display = showTopSearch ? "" : "none";
}

function appendChatErrorWithRetry(errorText, retryQuestion) {
  const row = window.CopilotChat?.appendBubble("chatHistory", "bot", errorText);
  if (!row || !retryQuestion) return;
  const wrap = document.createElement("div");
  wrap.className = "chat-error-actions";
  const retryBtn = document.createElement("button");
  retryBtn.type = "button";
  retryBtn.className = "ghost-btn chat-retry-btn";
  retryBtn.textContent = "Retry";
  retryBtn.addEventListener("click", () => {
    askQuestion(retryQuestion);
  });
  wrap.appendChild(retryBtn);
  row.appendChild(wrap);
}

async function refreshAll() {
  await fetchSummary();
  await fetchInvoices();
  renderCurrentReport();
}

function setupUploadDropzone() {
  const drop = document.getElementById("dropZone");
  const fileInput = document.getElementById("csvFile");
  drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    drop.classList.add("drag-over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("drag-over");
    if (event.dataTransfer.files && event.dataTransfer.files[0]) {
      fileInput.files = event.dataTransfer.files;
    }
  });
}

function setupLogin() {
  const loginPage = document.getElementById("loginPage");
  const shell = document.getElementById("appShell");
  const loginBtn = document.getElementById("loginBtn");
  const error = document.getElementById("loginError");
  loginBtn.addEventListener("click", async () => {
    const email = document.getElementById("loginEmail").value.trim().toLowerCase();
    const pass = document.getElementById("loginPassword").value;
    const acceptedUsers = new Set(["admin@financecopilot.com", "admin"]);
    if (!acceptedUsers.has(email) || pass !== "Admin@123") {
      error.textContent = "Invalid credentials. Use demo admin login.";
      return;
    }
    error.textContent = "";
    document.getElementById("uploadMsg").textContent = "";
    loginPage.classList.add("hidden");
    shell.classList.remove("hidden");
    window.CopilotChat?.appendBubble("chatHistory", "bot", "Hello Admin. Ask any invoice or risk question to start analysis.");
    await refreshAll();
  });
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchPage(btn.dataset.page));
});

document.querySelectorAll("button[data-report]").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.currentReportType = btn.dataset.report || "aging";
    renderCurrentReport();
  });
});

document.getElementById("downloadCurrentReport").addEventListener("click", () => {
  const reportName = state.currentReportType || "report";
  const filename = `${reportName}_report.csv`;
  downloadCsv(filename, state.currentReportRows);
});

document.getElementById("uploadBtn").addEventListener("click", async () => {
  try {
    await uploadCsv();
  } catch (err) {
    document.getElementById("uploadMsg").textContent = String(err);
    window.CopilotUI?.showToast(String(err), "error");
  }
});

document.getElementById("activatePreviewBtn")?.addEventListener("click", async () => {
  try {
    const target = state.pendingDatasetId || document.getElementById("activeDatasetSelector")?.value;
    if (!target) {
      document.getElementById("uploadMsg").textContent = "Upload a file first, then activate it.";
      return;
    }
    await activateDataset(target);
  } catch (err) {
    document.getElementById("uploadMsg").textContent = String(err);
    window.CopilotUI?.showToast(String(err), "error");
  }
});

document.getElementById("activeDatasetSelector")?.addEventListener("change", async (event) => {
  const id = event.target?.value;
  if (!id) return;
  try {
    await activateDataset(id);
  } catch (err) {
    document.getElementById("uploadMsg").textContent = String(err);
    window.CopilotUI?.showToast(String(err), "error");
  }
});

document.getElementById("refreshDatasetsBtn")?.addEventListener("click", async () => {
  try {
    await refreshDatasets();
  } catch (err) {
    document.getElementById("uploadMsg").textContent = String(err);
    window.CopilotUI?.showToast(String(err), "error");
  }
});

document.getElementById("askBtn").addEventListener("click", async () => {
  const input = document.getElementById("question");
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  try {
    await askQuestion(question);
  } catch (err) {
    window.CopilotChat?.appendBubble("chatHistory", "bot", String(err));
    window.CopilotUI?.showToast(String(err), "error");
  }
});

document.getElementById("question").addEventListener("keydown", async (event) => {
  if (event.key === "Enter") document.getElementById("askBtn").click();
});

document.querySelectorAll(".quick-actions button").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const q = btn.getAttribute("data-q");
    if (!q) return;
    document.getElementById("question").value = q;
    document.getElementById("askBtn").click();
  });
});

document.querySelectorAll("#copilotPromptCards .copilot-prompt-card").forEach((btn) => {
  btn.addEventListener("click", () => {
    const q = btn.getAttribute("data-q") || "";
    if (!q) return;
    document.getElementById("question").value = q;
    document.getElementById("askBtn").click();
  });
});

document.getElementById("refreshBtn").addEventListener("click", async () => {
  await refreshAll().catch((err) => {
    document.getElementById("dataStatusText").textContent = String(err);
  });
});

document.getElementById("searchInput").addEventListener("input", applyDashboardSearch);
document.getElementById("searchInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") applyDashboardSearch();
});
document.getElementById("dashboardStatusFilter")?.addEventListener("change", (event) => {
  state.dashboardFilters.status = event.target?.value || "all";
  state.dashboardDrilldown = { type: "", value: "" };
  renderDashboardCharts(state.records || []);
});
document.getElementById("dashboardTopN")?.addEventListener("change", (event) => {
  state.dashboardFilters.topNRegions = Number(event.target?.value || 8);
  renderDashboardCharts(state.records || []);
});
document.getElementById("clearDashboardDrilldownBtn")?.addEventListener("click", () => {
  state.dashboardDrilldown = { type: "", value: "" };
  renderDashboardCharts(state.records || []);
});

document.getElementById("todayDate").textContent = new Date().toLocaleDateString();
setupUploadDropzone();
setupLogin();
setActivateButtonEnabled(false);
refreshDatasets().catch(() => {});
window.CopilotChat?.ensureEmptyState("chatHistory");
