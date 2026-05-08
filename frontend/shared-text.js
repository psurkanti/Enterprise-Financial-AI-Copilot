/* Shared text formatting + markdown table helpers. */
(function initSharedText(global) {
  function sanitizeSummaryText(text) {
    const t = String(text || "").trim();
    if (!t) return t;
    let out = t;
    out = out.replace(
      /^\s*(enterprise financial ai copilot|our copilot)\s+(found|identified|located)\s+[\s\S]*?(?:\.\s*)?$/i,
      ""
    );
    out = out.replace(/found\s+\d+\s+matching\s+records\b[\s\S]*?(?:\.\s*)?$/i, "");
    out = out.replace(/\bmatching\s+records\b/i, "");
    return out.trim();
  }

  function parseMarkdownTable(text) {
    const lines = String(text || "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const tableStart = lines.findIndex(
      (line, idx) => line.includes("|") && idx + 1 < lines.length && /^\|?\s*[-:| ]+\|?\s*$/.test(lines[idx + 1])
    );
    if (tableStart < 0) return null;

    const rowLines = [];
    for (let i = tableStart; i < lines.length; i += 1) {
      if (!lines[i].includes("|")) break;
      rowLines.push(lines[i]);
    }
    if (rowLines.length < 2) return null;

    const parseRow = (row) =>
      row
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((cell) => cell.trim());

    const headers = parseRow(rowLines[0]);
    const dataRows = rowLines.slice(2).map(parseRow).filter((cells) => cells.length === headers.length);
    if (!headers.length || !dataRows.length) return null;
    return { headers, rows: dataRows };
  }

  function renderMarkdownTable(tableData) {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap copilot-inline-table";
    wrap.style.maxHeight = "220px";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const tbody = document.createElement("tbody");
    const hr = document.createElement("tr");
    tableData.headers.forEach((h) => {
      const th = document.createElement("th");
      th.textContent = h;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    tableData.rows.forEach((r) => {
      const tr = document.createElement("tr");
      r.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.append(thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }

  global.CopilotText = {
    sanitizeSummaryText,
    parseMarkdownTable,
    renderMarkdownTable,
  };
})(window);
