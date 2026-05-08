/** Same host/port as this page (works on any port, e.g. 8844 Desktop launcher). */
const apiBase = window.location.origin;
const state = {
  activeDataset: "None",
  summary: null,
  records: [],
  sessionId: sessionStorage.getItem("copilotSessionId") || "",
  /** True after /summary returns 200 — backend may already have active_invoices.csv before this browser session. */
  hasActiveDataset: false,
  currentReportType: "aging",
  currentReportRows: [],
};

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

function clearKpiPlaceholders() {
  document.getElementById("kpiTotalDue").textContent = "-";
  document.getElementById("kpiTotalInvoices").textContent = "-";
  document.getElementById("kpiOverdueInvoices").textContent = "-";
  document.getElementById("kpiHighRisk").textContent = "-";
  document.getElementById("kpiTopRegion").textContent = "-";
}

async function fetchSummary() {
  try {
    const res = await fetch(`${apiBase}/summary`, { cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      state.hasActiveDataset = false;
      state.summary = null;
      clearKpiPlaceholders();
      state.activeDataset = "None";
      document.getElementById("activeDataset").textContent = "None";
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
    document.getElementById("activeDataset").textContent = state.activeDataset;
    document.getElementById("kpiTotalDue").textContent = currency(data.total_due);
    document.getElementById("kpiTotalInvoices").textContent = data.total_invoices;
    document.getElementById("kpiOverdueInvoices").textContent = data.overdue_invoices;
    document.getElementById("kpiHighRisk").textContent = data.high_risk_customers;
    document.getElementById("kpiTopRegion").textContent = data.top_region_by_balance;
    document.getElementById("dataStatusText").textContent = `Active dataset: ${state.activeDataset} | ${data.total_invoices} records loaded`;
  } catch (err) {
    state.hasActiveDataset = false;
    state.summary = null;
    state.activeDataset = "None";
    document.getElementById("activeDataset").textContent = "None";
    clearKpiPlaceholders();
    document.getElementById("dataStatusText").textContent = String(err);
  }
}

async function fetchInvoices(limit = 200) {
  if (!state.hasActiveDataset) {
    state.records = [];
    renderRecentTable([]);
    renderPreviewTable([]);
    renderRegionChart([]);
    renderStatusChart([]);
    return;
  }
  try {
    const res = await fetch(`${apiBase}/invoices?limit=${limit}`, { cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      state.records = [];
      renderRecentTable([]);
      renderPreviewTable([]);
      renderRegionChart([]);
      renderStatusChart([]);
      document.getElementById("dataStatusText").textContent =
        typeof data.detail === "string" ? data.detail : "Failed to load invoice rows.";
      return;
    }
    state.records = data.records || [];
    renderRecentTable(state.records);
    renderPreviewTable(state.records.slice(0, 10));
    renderRegionChart(state.records);
    renderStatusChart(state.records);
  } catch (err) {
    state.records = [];
    renderRecentTable([]);
    renderPreviewTable([]);
    renderRegionChart([]);
    renderStatusChart([]);
    document.getElementById("dataStatusText").textContent = String(err);
  }
}

function renderRegionChart(records) {
  const container = document.getElementById("regionChart");
  const map = {};
  records.forEach((row) => {
    const key = row.region || "Unknown";
    map[key] = (map[key] || 0) + Number(row.invoice_amount_due || 0);
  });
  const entries = Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const max = entries.length ? entries[0][1] : 1;
  container.innerHTML = "";
  entries.forEach(([region, value]) => {
    const percent = Math.round((value / max) * 100);
    const row = document.createElement("div");
    row.className = "chart-row";
    row.innerHTML = `
      <span>${region}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${percent}%"></div></div>
      <strong>${currency(value)}</strong>
    `;
    container.appendChild(row);
  });
}

function renderStatusChart(records) {
  const container = document.getElementById("statusChart");
  const counts = { paid: 0, pending: 0, overdue: 0 };
  records.forEach((row) => {
    const k = String(row.status || "").toLowerCase();
    if (k in counts) counts[k] += 1;
    else counts.overdue += 1;
  });
  container.innerHTML = "";
  Object.entries(counts).forEach(([status, count]) => {
    const div = document.createElement("div");
    div.className = "pie-item";
    div.innerHTML = `<span>${status.toUpperCase()}</span><strong>${count}</strong>`;
    container.appendChild(div);
  });
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
    renderRecentTable(state.records);
    document.getElementById("dataStatusText").textContent = `Active dataset: ${state.activeDataset} | ${state.records.length} records loaded`;
    return;
  }

  const matches = state.records.filter((row) => {
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

function showTypingIndicator() {
  const chat = document.getElementById("chatHistory");
  const row = document.createElement("div");
  row.className = "copilot-typing-row";
  const avatar = document.createElement("span");
  avatar.className = "copilot-avatar";
  avatar.textContent = "✦";
  const dots = document.createElement("div");
  dots.className = "typing-dots";
  for (let i = 0; i < 3; i += 1) {
    dots.appendChild(document.createElement("span"));
  }
  row.append(avatar, dots);
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
  return row;
}

function buildInlineRecordsTable(records, maxHeightPx) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap copilot-inline-table";
  if (maxHeightPx) wrap.style.maxHeight = `${maxHeightPx}px`;
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const tbody = document.createElement("tbody");
  if (!records || records.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.textContent = "No matching rows for this answer.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    table.append(thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }
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
  table.append(thead, tbody);
  wrap.appendChild(table);
  return wrap;
}

function sanitizeSummaryText(text) {
  const t = String(text || "").trim();
  if (!t) return t;
  // JS does not support inline modifiers like (?is). Use [\s\S]*? to mimic dotall.
  let out = t;
  out = out.replace(
    /^\s*(enterprise financial ai copilot|our copilot)\s+(found|identified|located)\s+[\s\S]*?(?:\.\s*)?$/i,
    ""
  );
  out = out.replace(/found\s+\d+\s+matching\s+records\b[\s\S]*?(?:\.\s*)?$/i, "");
  out = out.replace(/\bmatching\s+records\b/i, "");
  return out.trim();
}

function appendStructuredCopilotMessage(data) {
  const chat = document.getElementById("chatHistory");
  const style = data.response_style || "direct";
  const records = data.matching_records || [];

  if (typeof data.summary === "string") data.summary = sanitizeSummaryText(data.summary);

  if (style === "direct") {
    const row = document.createElement("div");
    row.className = "chat-message-row bot";
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

  if (style === "analytical") {
    const block = document.createElement("article");
    block.className = "copilot-answer-block";
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

    chat.appendChild(block);
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  if (style === "records" && records.length === 0) {
    const row = document.createElement("div");
    row.className = "chat-message-row bot";
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
  block.className = "copilot-answer-block";

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
    secTbl.appendChild(buildInlineRecordsTable(records, 240));
    block.appendChild(secTbl);
  }

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
  appendChatBubble("user", question);
  const typing = showTypingIndicator();
  try {
    const res = await fetch(`${apiBase}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: state.sessionId || null }),
    });
    const data = await res.json();
    typing.remove();
    if (!res.ok) throw new Error(data.detail || "Ask failed");
    if (data.session_id) {
      state.sessionId = data.session_id;
      sessionStorage.setItem("copilotSessionId", state.sessionId);
    }
    appendStructuredCopilotMessage(data);
  } catch (err) {
    typing.remove();
    appendChatBubble("bot", String(err));
  }
}

async function uploadCsv() {
  const msg = document.getElementById("uploadMsg");
  const fileInput = document.getElementById("csvFile");
  if (!fileInput.files || fileInput.files.length === 0) {
    msg.textContent = "Please select a CSV file.";
    return;
  }
  const form = new FormData();
  form.append("file", fileInput.files[0]);
  const res = await fetch(`${apiBase}/upload-csv`, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Upload failed");
  state.sessionId = "";
  sessionStorage.removeItem("copilotSessionId");
  state.activeDataset = data.file || "active_invoices.csv";
  document.getElementById("activeDataset").textContent = state.activeDataset;
  const uploaded = data.rows != null ? ` Saved ${data.rows} rows.` : "";
  document.getElementById("uploadMsg").textContent = (data.message || "Upload successful.") + uploaded;
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

function appendChatBubble(role, text) {
  const chat = document.getElementById("chatHistory");
  const row = document.createElement("div");
  row.className = `chat-message-row ${role}`;
  if (role === "bot") {
    const avatar = document.createElement("span");
    avatar.className = "copilot-avatar small";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "✦";
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    div.textContent = text;
    row.append(avatar, div);
  } else {
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    div.textContent = text;
    row.appendChild(div);
  }
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
  return row;
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
    appendChatBubble("bot", "Hello Admin. Ask any invoice or risk question to start analysis.");
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
    appendChatBubble("bot", String(err));
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

document.getElementById("todayDate").textContent = new Date().toLocaleDateString();
setupUploadDropzone();
setupLogin();
