/* ── app.js — Mini AI BI Assistant ─────────────────────────────────
   Handles:
     • Light/dark mode (localStorage)
     • KPI cards from GET /api/kpis
     • Question form + chip buttons + char counter + Enter submit
     • POST /api/query response rendering:
         - mode badge (llm | deterministic | none)
         - status banner (rejected / out_of_domain / error)
         - answer text (with basic markdown bold)
         - line chart, bar chart, metric_card, or table chart type
         - data table from table_data
         - collapsible SQL + reasoning trace
   ─────────────────────────────────────────────────────────────────── */
'use strict';

// ── Theme ────────────────────────────────────────────────────────────
(function () {
  const saved = localStorage.getItem('bi-theme') || 'light';
  document.getElementById('body').className = saved;
  document.getElementById('themeIcon').textContent = saved === 'dark' ? '☀️' : '🌙';
})();

document.getElementById('themeToggle').addEventListener('click', () => {
  const body = document.getElementById('body');
  const icon = document.getElementById('themeIcon');
  const isDark = body.classList.toggle('dark');
  body.classList.toggle('light', !isDark);
  localStorage.setItem('bi-theme', isDark ? 'dark' : 'light');
  icon.textContent = isDark ? '☀️' : '🌙';
});

// ── KPI Cards ─────────────────────────────────────────────────────────
async function loadKPIs() {
  try {
    const r = await fetch('/api/kpis');
    if (!r.ok) return;
    const d = await r.json();
    setText('kpi-revenue-val', '$' + fmt(d.total_revenue));
    setText('kpi-orders', d.completed_orders + ' completed orders');
    setText('kpi-units-val', fmtInt(d.total_units_sold));
    setText('kpi-product-val', d.top_product);
    setText('kpi-product-rev', '$' + fmt(d.top_product_revenue) + ' net');
    setText('kpi-region-val', d.top_region);
    setText('kpi-region-rev', '$' + fmt(d.top_region_revenue) + ' net');
  } catch (_) { /* silently continue — KPI load failure is non-critical */ }
}
loadKPIs();

// ── Chips ─────────────────────────────────────────────────────────────
document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.getElementById('questionInput').value = chip.dataset.q;
    updateCharCount();
    document.getElementById('askForm').dispatchEvent(new Event('submit'));
  });
});

// ── Char counter ─────────────────────────────────────────────────────
const qInput = document.getElementById('questionInput');
qInput.addEventListener('input', updateCharCount);
function updateCharCount() {
  const len = qInput.value.length;
  const el = document.getElementById('charCount');
  el.textContent = len + ' / 500';
  el.style.color = len > 480 ? '#ef4444' : '';
}

// ── Form submit ───────────────────────────────────────────────────────
document.getElementById('askForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = qInput.value.trim();
  if (!question) return;

  if (question.length > 500) {
    showError('Question is too long (' + question.length + ' chars). Max 500.');
    return;
  }

  hideError();
  showSpinner(true);
  showEmpty(false);
  hideAnswer();

  try {
    const r = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });

    if (r.status === 422) {
      const err = await r.json();
      const detail = err.detail?.[0]?.msg || 'Validation error — question may be too long.';
      showError(detail);
      return;
    }
    if (!r.ok) {
      showError('Server error (' + r.status + '). Please try again.');
      return;
    }

    const data = await r.json();
    renderAnswer(data);
  } catch (err) {
    showError('Network error — is the server running? (' + err.message + ')');
  } finally {
    showSpinner(false);
  }
});

// ── Render answer ─────────────────────────────────────────────────────
let chartInstance = null;

function renderAnswer(d) {
  // Status banner
  const banner = document.getElementById('statusBanner');
  banner.className = 'status-banner';
  const nonSuccess = ['rejected', 'out_of_domain', 'error', 'invalid_request'];
  if (nonSuccess.includes(d.status)) {
    const labels = {
      rejected: '🚫 Request rejected — SQL injection pattern detected in question.',
      out_of_domain: '🔍 Out of scope — this assistant covers sales data only.',
      error: '⚠️ An error occurred.',
      invalid_request: '⚠️ Invalid request.',
    };
    banner.textContent = labels[d.status] || d.status;
    banner.classList.add(d.status, 'visible');
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }

  // Mode badge
  const wrap = document.getElementById('modeBadgeWrap');
  wrap.innerHTML = '';
  if (d.mode === 'llm') {
    wrap.innerHTML = '<span class="badge badge-llm" title="Answered by Gemini LLM — SQL validated before execution">🤖 LLM</span>';
  } else if (d.mode === 'deterministic') {
    wrap.innerHTML = '<span class="badge badge-det" title="Answered by verified deterministic SQL">✅ Deterministic</span>';
  }

  // Question + answer
  setText('answerQuestion', '"' + d.question + '"');
  const bodyEl = document.getElementById('answerBody');
  bodyEl.innerHTML = renderMarkdown(d.answer || '');

  // Metric card / chart / table
  toggleEl('metricCard', false);
  toggleEl('chartWrap', false);
  toggleEl('tableWrap', false);

  if (d.chart_type === 'metric_card' && d.supporting_figures) {
    const figures = d.supporting_figures;
    const firstKey = Object.keys(figures)[0];
    const firstVal = figures[firstKey];
    document.getElementById('metricValue').textContent = fmtValue(firstKey, firstVal);
    document.getElementById('metricLabel').textContent = friendlyKey(firstKey);
    toggleEl('metricCard', true);
  } else if ((d.chart_type === 'line' || d.chart_type === 'bar') && d.chart_config) {
    renderChart(d.chart_type, d.chart_config);
    toggleEl('chartWrap', true);
  }

  // Data table (shown for all types with table_data)
  if (d.table_data && d.table_data.length > 0) {
    buildTable(d.table_data);
    toggleEl('tableWrap', true);
  }

  // SQL + reasoning
  const sql = d.sql_query || '';
  document.querySelector('#sqlBlock code').textContent = sql || '(no SQL executed)';

  const traceList = document.getElementById('traceList');
  traceList.innerHTML = '';
  (d.reasoning_trace || []).forEach(step => {
    const li = document.createElement('li');
    li.innerHTML = '<strong>' + esc(step.step) + ':</strong> ' + esc(step.detail);
    traceList.appendChild(li);
  });

  setText('execTime', d.execution_time_ms + ' ms');
  setText('dataNote', d.data_quality_note || '');

  showAnswer();
}

// ── Chart ─────────────────────────────────────────────────────────────
function renderChart(type, config) {
  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
  const ctx = document.getElementById('mainChart').getContext('2d');
  const isDark = document.getElementById('body').classList.contains('dark');
  const gridColor = isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.07)';
  const tickColor = isDark ? '#a0a0c0' : '#555568';
  const accent = '#6366f1';
  const accentFill = type === 'line' ? 'rgba(99,102,241,0.12)' : accent;

  chartInstance = new Chart(ctx, {
    type: type,
    data: {
      labels: config.labels,
      datasets: [{
        label: config.series_name || 'Value',
        data: config.values,
        backgroundColor: type === 'bar'
          ? config.values.map((_, i) => `hsl(${240 + i * 22},70%,${isDark ? 55 : 50}%)`)
          : accentFill,
        borderColor: accent,
        borderWidth: type === 'line' ? 2.5 : 0,
        borderRadius: type === 'bar' ? 6 : 0,
        pointBackgroundColor: accent,
        pointRadius: type === 'line' ? 4 : 0,
        fill: type === 'line',
        tension: 0.38,
      }],
    },
    options: {
      responsive: true,
      animation: { duration: 500 },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const v = ctx.parsed.y;
              return typeof v === 'number' && v > 100
                ? ' $' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                : ' ' + v;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: tickColor, maxRotation: 45 },
          grid: { color: gridColor },
        },
        y: {
          ticks: {
            color: tickColor,
            callback: (v) => typeof v === 'number' && v >= 1000 ? '$' + (v / 1000).toFixed(0) + 'k' : v,
          },
          grid: { color: gridColor },
        },
      },
    },
  });
}

// ── Table ─────────────────────────────────────────────────────────────
function buildTable(rows) {
  const keys = Object.keys(rows[0]);
  const head = document.getElementById('tableHead');
  const body = document.getElementById('tableBody');

  head.innerHTML = '<tr>' + keys.map(k =>
    '<th>' + friendlyKey(k) + '</th>'
  ).join('') + '</tr>';

  body.innerHTML = rows.map(row =>
    '<tr>' + keys.map(k => {
      const v = row[k];
      const isNum = typeof v === 'number';
      const isMoney = /revenue|amount|price|discount|gross|net|cost/i.test(k);
      const cell = isNum && isMoney
        ? '$' + fmt(v)
        : isNum
          ? fmtInt(v)
          : esc(String(v ?? ''));
      return '<td' + (isNum ? ' class="num"' : '') + '>' + cell + '</td>';
    }).join('') + '</tr>'
  ).join('');
}

// ── Helpers ────────────────────────────────────────────────────────────
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function toggleEl(id, show) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('hidden', !show);
}

function showSpinner(show) {
  toggleEl('spinner', show);
  document.getElementById('submitBtn').disabled = show;
}

function showEmpty(show) { toggleEl('emptyState', show); }

function showAnswer() {
  document.getElementById('emptyState').classList.add('hidden');
  document.getElementById('answerCard').classList.remove('hidden');
}

function hideAnswer() {
  document.getElementById('answerCard').classList.add('hidden');
}

function showError(msg) {
  document.getElementById('errorMsg').textContent = msg;
  document.getElementById('errorBanner').classList.remove('hidden');
}

function hideError() {
  document.getElementById('errorBanner').classList.add('hidden');
}

function fmt(n) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtInt(n) {
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function fmtValue(colName, val) {
  if (typeof val !== 'number') return String(val);
  const col = colName.toLowerCase();
  if (/revenue|amount|price|discount|gross|net|cost/.test(col)) return '$' + fmt(val);
  if (/pct|percent|rate/.test(col)) return val.toFixed(2) + '%';
  return Number.isInteger(val) ? fmtInt(val) : fmt(val);
}

function friendlyKey(k) {
  return k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Basic **bold** markdown → <strong>
function renderMarkdown(text) {
  return esc(text).replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
}
