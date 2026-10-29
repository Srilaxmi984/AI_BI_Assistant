let chartInstance = null;

document.addEventListener("DOMContentLoaded", () => {
  loadKPIs();
  setupEventListeners();
});

// Fetch and display headline KPIs
async function loadKPIs() {
  try {
    const res = await fetch("/api/kpis");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("kpiRevenue").textContent = formatCurrency(data.total_revenue);
    document.getElementById("kpiRevenueSub").textContent = `Gross: ${formatCurrency(data.gross_revenue)} | Discounts: ${formatCurrency(data.total_discounts)}`;
    
    document.getElementById("kpiOrders").textContent = data.completed_orders.toLocaleString();
    document.getElementById("kpiUnits").textContent = `${data.total_units_sold.toLocaleString()} units sold`;

    document.getElementById("kpiTopProduct").textContent = data.top_product;
    document.getElementById("kpiTopProductRev").textContent = formatCurrency(data.top_product_revenue);

    document.getElementById("kpiTopRegion").textContent = data.top_region;
    document.getElementById("kpiTopRegionRev").textContent = formatCurrency(data.top_region_revenue);
  } catch (err) {
    console.error("Failed to load KPIs:", err);
  }
}

// Event Listeners
function setupEventListeners() {
  const askBtn = document.getElementById("askBtn");
  const input = document.getElementById("questionInput");
  const chips = document.querySelectorAll(".chip");
  const copyBtn = document.getElementById("copySqlBtn");

  askBtn.addEventListener("click", () => handleQuery(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleQuery(input.value);
  });

  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      const q = chip.getAttribute("data-q");
      input.value = q;
      handleQuery(q);
    });
  });

  copyBtn.addEventListener("click", () => {
    const sql = document.getElementById("sqlQueryText").textContent;
    navigator.clipboard.writeText(sql).then(() => {
      copyBtn.textContent = "Copied!";
      setTimeout(() => { copyBtn.textContent = "Copy SQL"; }, 2000);
    });
  });
}

// Handle User Query Submission
async function handleQuery(question) {
  if (!question || !question.trim()) return;

  const loadingIndicator = document.getElementById("loadingIndicator");
  const resultsSection = document.getElementById("resultsSection");

  loadingIndicator.classList.remove("hidden");
  resultsSection.classList.add("hidden");

  try {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question.trim() })
    });

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    const data = await res.json();
    renderResults(data);
  } catch (err) {
    alert("Query failed: " + err.message);
  } finally {
    loadingIndicator.classList.add("hidden");
  }
}

// Render Results
function renderResults(data) {
  const resultsSection = document.getElementById("resultsSection");
  resultsSection.classList.remove("hidden");

  // Latency & Answer
  document.getElementById("latencyBadge").textContent = `${data.execution_time_ms} ms`;
  document.getElementById("answerText").innerHTML = formatMarkdown(data.answer);

  // Data Quality Note
  const qualityAlert = document.getElementById("dataQualityAlert");
  if (data.data_quality_note) {
    qualityAlert.textContent = `ℹ️ ${data.data_quality_note}`;
    qualityAlert.classList.remove("hidden");
  } else {
    qualityAlert.classList.add("hidden");
  }

  // Supporting Figures
  renderSupportingFigures(data.supporting_figures);

  // Executed SQL
  document.getElementById("sqlQueryText").textContent = data.sql_query || "-- No SQL query generated for this response";

  // Data Table
  renderTable(data.table_data);

  // Chart Rendering
  renderChart(data);

  // ReAct Trace
  renderTrace(data.reasoning_trace);

  // Smooth scroll into view
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Helper: Format Markdown bold & bullets
function formatMarkdown(text) {
  if (!text) return "";
  let formatted = text
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/\n\n/g, "<br><br>")
    .replace(/\n/g, "<br>");
  return formatted;
}

// Helper: Format Currency
function formatCurrency(num) {
  if (num === null || num === undefined) return "$0.00";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(num);
}

// Render Supporting Figures
function renderSupportingFigures(figures) {
  const container = document.getElementById("figuresGrid");
  container.innerHTML = "";

  if (!figures || Object.keys(figures).length === 0) {
    container.innerHTML = "<p style='color: var(--text-muted); font-size: 0.85rem;'>No scalar supporting figures returned.</p>";
    return;
  }

  for (const [key, val] of Object.entries(figures)) {
    // Skip nested arrays or objects
    if (typeof val === "object" && val !== null) continue;

    const box = document.createElement("div");
    box.className = "figure-box";

    const label = document.createElement("div");
    label.className = "figure-box-label";
    label.textContent = key.replace(/_/g, " ");

    const value = document.createElement("div");
    value.className = "figure-box-val";

    if (typeof val === "number") {
      if (key.includes("revenue") || key.includes("price") || key.includes("discount") || key.includes("change")) {
        value.textContent = formatCurrency(val);
      } else if (key.includes("pct") || key.includes("percent") || key.includes("share")) {
        value.textContent = `${val}%`;
      } else {
        value.textContent = val.toLocaleString();
      }
    } else {
      value.textContent = String(val);
    }

    box.appendChild(label);
    box.appendChild(value);
    container.appendChild(box);
  }
}

// Render Tabular Data
function renderTable(rows) {
  const tableHead = document.getElementById("tableHead");
  const tableBody = document.getElementById("tableBody");
  const rowCountBadge = document.getElementById("rowCountBadge");
  const tableCard = document.getElementById("tableCard");

  tableHead.innerHTML = "";
  tableBody.innerHTML = "";

  if (!rows || rows.length === 0) {
    tableCard.classList.add("hidden");
    return;
  }

  tableCard.classList.remove("hidden");
  rowCountBadge.textContent = `${rows.length} record${rows.length === 1 ? '' : 's'}`;

  const headers = Object.keys(rows[0]);
  const trHead = document.createElement("tr");
  headers.forEach((h) => {
    const th = document.createElement("th");
    th.textContent = h.replace(/_/g, " ");
    trHead.appendChild(th);
  });
  tableHead.appendChild(trHead);

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    headers.forEach((h) => {
      const td = document.createElement("td");
      const val = row[h];
      if (typeof val === "number" && (h.includes("revenue") || h.includes("price") || h.includes("discount"))) {
        td.textContent = formatCurrency(val);
        td.style.fontWeight = "600";
      } else {
        td.textContent = val !== null && val !== undefined ? val : "-";
      }
      tr.appendChild(td);
    });
    tableBody.appendChild(tr);
  });
}

// Render Chart with Chart.js
function renderChart(data) {
  const chartCard = document.getElementById("chartCard");
  const ctx = document.getElementById("biChart").getContext("2d");

  if (!data.chart_config || !data.chart_config.labels || data.chart_config.labels.length === 0) {
    chartCard.classList.add("hidden");
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
    return;
  }

  chartCard.classList.remove("hidden");

  if (chartInstance) {
    chartInstance.destroy();
  }

  const isLine = data.chart_type === "line";
  const labels = data.chart_config.labels;
  const values = data.chart_config.values;
  const seriesName = data.chart_config.series_name || "Revenue ($)";

  // Gradient fill for sleek UI
  const gradient = ctx.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, "rgba(99, 102, 241, 0.7)");
  gradient.addColorStop(1, "rgba(56, 189, 248, 0.1)");

  chartInstance = new Chart(ctx, {
    type: isLine ? "line" : "bar",
    data: {
      labels: labels,
      datasets: [{
        label: seriesName,
        data: values,
        backgroundColor: isLine ? gradient : "rgba(99, 102, 241, 0.8)",
        borderColor: "#38bdf8",
        borderWidth: 2,
        borderRadius: isLine ? 0 : 8,
        tension: 0.35,
        fill: isLine,
        pointBackgroundColor: "#38bdf8",
        pointBorderColor: "#ffffff",
        pointRadius: 5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          labels: { color: "#94a3b8", font: { family: "Inter", size: 12 } }
        },
        tooltip: {
          backgroundColor: "rgba(15, 23, 42, 0.95)",
          titleColor: "#f8fafc",
          bodyColor: "#38bdf8",
          borderColor: "#334155",
          borderWidth: 1,
          padding: 12,
          callbacks: {
            label: function(context) {
              return ` ${context.dataset.label}: ${formatCurrency(context.parsed.y)}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#94a3b8", font: { family: "Inter" } }
        },
        y: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: {
            color: "#94a3b8",
            font: { family: "Inter" },
            callback: function(val) {
              return formatCurrency(val);
            }
          }
        }
      }
    }
  });
}

// Render ReAct Reasoning Trace
function renderTrace(trace) {
  const container = document.getElementById("traceTimeline");
  container.innerHTML = "";

  if (!trace || trace.length === 0) {
    container.innerHTML = "<p style='color: var(--text-muted); font-size: 0.85rem;'>No trace available.</p>";
    return;
  }

  trace.forEach((t) => {
    const stepDiv = document.createElement("div");
    stepDiv.className = "trace-step";

    const tag = document.createElement("span");
    tag.className = `trace-tag tag-${t.step.toLowerCase()}`;
    tag.textContent = t.step;

    const text = document.createElement("div");
    text.className = "trace-text";
    text.textContent = t.detail;

    stepDiv.appendChild(tag);
    stepDiv.appendChild(text);
    container.appendChild(stepDiv);
  });
}
