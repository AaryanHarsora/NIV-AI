// 13. VERDICT RENDERER
// ════════════════════════════════════════════════════
function renderVerdict() {
  const r = backendResults;
  if (!r) { showToast('No analysis results available'); return; }

  const fr  = r.financial_reality || {};
  const hc  = r.hidden_costs      || {};
  const ra  = r.risk_assessment   || {};
  const v   = r.verdict           || {};
  const now = new Date().toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });

  // Meta
  document.getElementById('v-meta').textContent = `Session: ${session_id} | Generated: ${now}`;

  // Verdict badge
  const badge    = document.getElementById('v-go-badge');
  const decision = v.decision || '—';
  badge.className = `go-badge ${decision === 'GO' ? 'go' : 'nogo'}`;
  badge.innerHTML = `${decision}<span class="go-sub">${decision === 'GO' ? 'PROCEED WITH CAUTION' : 'AVOID COMMITMENT'}</span>`;

  // Confidence
  const conf = v.confidence || 0;
  document.getElementById('v-confidence').textContent = (conf * 100).toFixed(0) + '%';
  setTimeout(() => { document.getElementById('v-conf-bar').style.width = (conf * 100) + '%'; }, 200);

  // Reasoning
  document.getElementById('v-reasoning').innerHTML = `<strong>Analysis Summary:</strong> ${v.reasoning || 'No reasoning provided.'}`;

  // Financial Reality
  document.getElementById('v-emi').textContent = fmt(fr.emi);
  const emiRatio = fr.emi_to_income_ratio || 0;
  const ratioEl  = document.getElementById('v-emi-ratio');
  ratioEl.textContent = (emiRatio * 100).toFixed(1) + '%';
  ratioEl.className   = 'stat-val ' + (emiRatio > 0.4 ? 'warn' : emiRatio > 0.3 ? 'ok' : 'safe');
  const surplus   = fr.monthly_surplus || 0;
  const surplusEl = document.getElementById('v-surplus');
  surplusEl.textContent = fmt(surplus);
  surplusEl.className   = 'stat-val ' + (surplus < 0 ? 'warn' : 'safe');
  document.getElementById('v-loan').textContent = fmt(fr.loan_amount);

  const affordStatus = (fr.affordability_status || '').toUpperCase();
  const affordClass  = affordStatus === 'AFFORDABLE' ? 'affordable' : affordStatus === 'STRETCHED' ? 'stretched' : 'unaffordable';
  document.getElementById('v-afford-badge').innerHTML = `<span class="affordability-badge ${affordClass}">${affordStatus || '—'}</span>`;

  // Hidden Costs
  document.getElementById('v-base').textContent  = fmt(hc.base_price || hc.property_price);
  document.getElementById('v-gst').textContent   = fmt(hc.gst);
  document.getElementById('v-stamp').textContent = fmt(hc.stamp_duty);
  document.getElementById('v-reg').textContent   = fmt(hc.registration);
  document.getElementById('v-total').textContent = fmt(hc.total_cost);

  // Risk Score
  const score    = ra.composite_score || 0;
  const riskLabel = (ra.risk_label || 'MEDIUM').toLowerCase();
  const scoreEl   = document.getElementById('v-risk-score');
  scoreEl.textContent = score;
  scoreEl.className   = `risk-score-display ${riskLabel}`;
  document.getElementById('v-risk-label').innerHTML = `<span class="risk-label-badge ${riskLabel}">${(ra.risk_label || '—').toUpperCase()} RISK</span>`;
  const factorsEl = document.getElementById('v-risk-factors');
  factorsEl.innerHTML = ra.factors?.length
    ? ra.factors.map(f => `<div class="risk-factor-row"><div class="rf-dot ${f.triggered ? 'triggered' : 'clear'}"></div><span>${f.label}</span></div>`).join('')
    : '<div style="font-size:0.62rem;color:#888">No factor data.</div>';

  // Scenarios
  const scenEl = document.getElementById('v-scenarios');
  scenEl.innerHTML = r.scenarios?.length
    ? r.scenarios.map(s => {
        const sev     = (s.severity || 'MODERATE').toUpperCase();
        const sevClass = sev === 'CRITICAL' ? 'critical' : sev === 'LOW' || sev === 'SAFE' ? 'safe' : 'moderate';
        return `<div class="scenario-card ${sevClass}">
          <div class="scenario-title">${s.name || 'Scenario'}</div>
          <div class="scenario-desc">${s.description || ''}</div>
          <div class="scenario-badges">
            <span class="s-badge">${sev}</span>
            ${s.survivable !== undefined ? `<span class="s-badge">${s.survivable ? '✓ Survivable' : '✗ Critical'}</span>` : ''}
            ${s.buffer_months !== undefined ? `<span class="s-badge">Buffer: ${s.buffer_months} mo.</span>` : ''}
          </div>
        </div>`;
      }).join('')
    : '<div style="font-size:0.62rem;color:#888">No scenario data.</div>';

  // Report sub
  document.getElementById('v-report-sub').textContent = `Session ${session_id} — PDF generation available`;

  // Render charts (deferred for DOM paint)
  setTimeout(() => renderAllCharts(), 150);
}

// ════════════════════════════════════════════════════
// 14. CHARTS
// ════════════════════════════════════════════════════
function renderAllCharts() {
  if (!backendResults) return;
  drawCashFlowChart();
  drawEMIGauge();
  drawCostDonut();
  drawScenarioChart();
}

function getChartCtx(id) {
  const canvas = document.getElementById(id);
  if (!canvas) return null;
  const W = canvas.parentElement.offsetWidth || 300;
  canvas.width  = W;
  // height set by HTML attribute
  return { ctx: canvas.getContext('2d'), W, H: canvas.height };
}

/* ── CHART 1: CASH FLOW (line chart) ── */
function drawCashFlowChart() {
  const canvas = document.getElementById('chart-cashflow');
  if (!canvas) return;
  const wrap = canvas.parentElement;
  const W = wrap.offsetWidth || 340;
  const H = 180;
  canvas.width  = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');

  const fr  = backendResults.financial_reality || {};
  const inp = userInput || {};

  const income   = inp.monthly_income   || fr.emi + Math.abs(fr.monthly_surplus || 0) + (inp.monthly_expenses || 0);
  const expenses = inp.monthly_expenses || 0;
  const emi      = fr.emi || 0;
  const surplus  = fr.monthly_surplus || income - expenses - emi;

  const PAD = { top: 20, right: 20, bottom: 36, left: 64 };
  const pw  = W - PAD.left - PAD.right;
  const ph  = H - PAD.top - PAD.bottom;

  const months   = 12;
  const maxVal   = income * 1.05;
  const minVal   = Math.min(0, surplus) * 1.1;
  const valRange = maxVal - minVal;

  function xPos(i) { return PAD.left + (i / (months - 1)) * pw; }
  function yPos(v) { return PAD.top + ph - ((v - minVal) / valRange) * ph; }

  // Background
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, W, H);

  // Horizontal grid lines
  ctx.strokeStyle = '#f0f0f0';
  ctx.lineWidth   = 1;
  const gridSteps = 4;
  for (let i = 0; i <= gridSteps; i++) {
    const val = minVal + (valRange / gridSteps) * i;
    const y   = yPos(val);
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(W - PAD.right, y);
    ctx.stroke();
    // Y-axis labels
    ctx.fillStyle   = '#888';
    ctx.font        = '9px Space Mono, monospace';
    ctx.textAlign   = 'right';
    ctx.textBaseline = 'middle';
    const label = Math.abs(val) >= 100000
      ? `₹${(val / 100000).toFixed(1)}L`
      : `₹${Math.round(val / 1000)}k`;
    ctx.fillText(label, PAD.left - 6, y);
  }

  // Zero line
  if (minVal < 0) {
    ctx.strokeStyle = '#ddd';
    ctx.lineWidth   = 2;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(PAD.left, yPos(0));
    ctx.lineTo(W - PAD.right, yPos(0));
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // X-axis labels (months)
  ctx.fillStyle   = '#888';
  ctx.font        = '9px Space Mono, monospace';
  ctx.textAlign   = 'center';
  ctx.textBaseline = 'top';
  for (let i = 0; i < months; i++) {
    if (i % 3 === 0 || i === months - 1) {
      ctx.fillText(`M${i + 1}`, xPos(i), H - PAD.bottom + 8);
    }
  }

  // Draw income line (trust blue solid)
  function drawLine(color, lw, dash, getValue) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth   = lw;
    ctx.setLineDash(dash);
    for (let i = 0; i < months; i++) {
      const x = xPos(i);
      const y = yPos(getValue(i));
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Surplus fill area
  ctx.beginPath();
  for (let i = 0; i < months; i++) {
    const x = xPos(i);
    const y = yPos(surplus);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.lineTo(xPos(months - 1), yPos(0));
  ctx.lineTo(xPos(0), yPos(0));
  ctx.closePath();
  ctx.fillStyle = surplus >= 0 ? 'rgba(6,95,70,0.08)' : 'rgba(153,27,27,0.08)';
  ctx.fill();

  drawLine('#1e3a8a', 2, [],      () => income);
  drawLine('#991b1b', 2, [],      () => expenses + emi);
  drawLine('#065f46', 2, [6, 4], () => surplus);

  // Dots at data points for income and expense
  [[income, '#1e3a8a'], [expenses + emi, '#991b1b'], [surplus, '#065f46']].forEach(([val, color]) => {
    ctx.beginPath();
    ctx.arc(xPos(0), yPos(val), 3, 0, Math.PI * 2);
    ctx.arc(xPos(11), yPos(val), 3, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  });
}

/* ── CHART 2: EMI GAUGE (semicircle) ── */
function drawEMIGauge() {
  const canvas = document.getElementById('chart-gauge');
  if (!canvas) return;
  const ratio = backendResults.financial_reality?.emi_to_income_ratio || 0;
  const W = canvas.width, H = canvas.height;
  const ctx = canvas.getContext('2d');

  ctx.clearRect(0, 0, W, H);

  const cx = W / 2;
  const cy = H - 16;
  const r  = Math.min(W / 2 - 14, H - 24);

  // Draw colored zones (π to 0 = left to right)
  const zones = [
    { from: Math.PI,         to: Math.PI * 1.33, color: '#dcfce7', label: 'SAFE' },
    { from: Math.PI * 1.33,  to: Math.PI * 1.6,  color: '#fef9c3', label: 'OK' },
    { from: Math.PI * 1.6,   to: Math.PI * 2,    color: '#fee2e2', label: 'RISK' },
  ];
  zones.forEach(zone => {
    ctx.beginPath();
    ctx.arc(cx, cy, r, zone.from, zone.to, false);
    ctx.arc(cx, cy, r - 20, zone.to, zone.from, true);
    ctx.closePath();
    ctx.fillStyle = zone.color;
    ctx.fill();
    ctx.strokeStyle = '#111';
    ctx.lineWidth = 1;
    ctx.stroke();
  });

  // Zone labels
  ctx.font = 'bold 8px Space Mono, monospace';
  ctx.textAlign = 'center';
  ctx.fillStyle = '#555';
  ctx.fillText('SAFE', cx - r * 0.7, cy - 8);
  ctx.fillText('OK',   cx,           cy - r + 12);
  ctx.fillText('RISK', cx + r * 0.7, cy - 8);

  // Needle
  const clampedRatio = Math.min(ratio, 0.6);
  const needleAngle = Math.PI + (clampedRatio / 0.6) * Math.PI;
  const nx = cx + (r - 10) * Math.cos(needleAngle);
  const ny = cy + (r - 10) * Math.sin(needleAngle);

  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(nx, ny);
  ctx.strokeStyle = '#111';
  ctx.lineWidth = 3;
  ctx.stroke();

  // Center dot
  ctx.beginPath();
  ctx.arc(cx, cy, 5, 0, Math.PI * 2);
  ctx.fillStyle = '#111';
  ctx.fill();

  // Value display
  ctx.font = 'bold 13px Space Mono, monospace';
  ctx.textAlign = 'center';
  ctx.fillStyle = ratio > 0.4 ? '#991b1b' : ratio > 0.3 ? '#b45309' : '#065f46';
  ctx.fillText(`${(ratio * 100).toFixed(1)}%`, cx, cy - 30);

  // Update label below
  const gaugeLabel = document.getElementById('gauge-label');
  if (gaugeLabel) {
    gaugeLabel.textContent = ratio > 0.4
      ? '⚠ EXCEEDS RBI LIMIT'
      : ratio > 0.3
      ? 'CAUTIONARY ZONE'
      : '✓ WITHIN SAFE BOUNDS';
    gaugeLabel.style.color = ratio > 0.4 ? '#991b1b' : ratio > 0.3 ? '#b45309' : '#065f46';
  }
}

/* ── CHART 3: COST DONUT ── */
function drawCostDonut() {
  const canvas = document.getElementById('chart-donut');
  if (!canvas) return;
  const hc  = backendResults.hidden_costs || {};
  const W   = canvas.width, H = canvas.height;
  const ctx = canvas.getContext('2d');

  ctx.clearRect(0, 0, W, H);

  const base  = hc.base_price      || 0;
  const gst   = hc.gst             || 0;
  const stamp = hc.stamp_duty      || 0;
  const reg   = hc.registration    || 0;
  const total = base + gst + stamp + reg;

  if (total === 0) return;

  const slices = [
    { label: 'Base',  value: base,  color: '#1e3a8a' },
    { label: 'Stamp', value: stamp, color: '#991b1b' },
    { label: 'GST',   value: gst,   color: '#b45309' },
    { label: 'Reg',   value: reg,   color: '#065f46' },
  ].filter(s => s.value > 0);

  const cx = W / 2;
  const cy = H / 2 - 4;
  const r  = Math.min(cx, cy) - 8;
  const ir = r * 0.52; // inner radius (donut hole)

  let startAngle = -Math.PI / 2;
  slices.forEach(slice => {
    const sweep = (slice.value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, startAngle + sweep, false);
    ctx.arc(cx, cy, ir, startAngle + sweep, startAngle, true);
    ctx.closePath();
    ctx.fillStyle   = slice.color;
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth   = 2;
    ctx.stroke();
    startAngle += sweep;
  });

  // Center text
  ctx.fillStyle   = '#111';
  ctx.font        = 'bold 9px Space Mono, monospace';
  ctx.textAlign   = 'center';
  ctx.textBaseline = 'middle';
  const totalL = total >= 10000000
    ? `₹${(total / 10000000).toFixed(1)}Cr`
    : total >= 100000
    ? `₹${(total / 100000).toFixed(1)}L`
    : fmt(total);
  ctx.fillText(totalL, cx, cy - 5);
  ctx.font      = '7px Space Mono, monospace';
  ctx.fillStyle = '#888';
  ctx.fillText('TOTAL', cx, cy + 8);

  // Legend below
  const legendEl = document.getElementById('donut-legend');
  if (legendEl) {
    legendEl.innerHTML = slices.map(s => {
      const pct = ((s.value / total) * 100).toFixed(1);
      return `<div class="legend-item"><div class="legend-dot" style="background:${s.color};display:inline-block;width:8px;height:8px;margin-right:4px"></div>${s.label} ${pct}%</div>`;
    }).join('');
    legendEl.style.display = 'flex';
    legendEl.style.flexWrap = 'wrap';
    legendEl.style.gap = '6px';
    legendEl.style.justifyContent = 'center';
    legendEl.style.marginTop = '6px';
    legendEl.style.fontSize = '0.5rem';
    legendEl.style.letterSpacing = '0.05em';
    legendEl.style.color = '#666';
  }
}

/* ── CHART 4: SCENARIO BARS (horizontal) ── */
function drawScenarioChart() {
  const canvas = document.getElementById('chart-scenarios');
  if (!canvas) return;
  const scenarios = backendResults.scenarios || [];
  if (scenarios.length === 0) return;

  const wrap = canvas.parentElement;
  const W = wrap.offsetWidth - 32 || 300;
  const H = 130;
  canvas.width  = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, W, H);

  const PAD  = { top: 12, right: 20, bottom: 20, left: 160 };
  const ph   = H - PAD.top - PAD.bottom;
  const pw   = W - PAD.left - PAD.right;
  const barH = Math.min(24, (ph / scenarios.length) - 6);
  const maxBuf = Math.max(...scenarios.map(s => s.buffer_months || 0), 12);

  const sevColors = { CRITICAL: '#991b1b', MODERATE: '#b45309', LOW: '#065f46', SAFE: '#065f46' };

  scenarios.forEach((s, i) => {
    const y      = PAD.top + i * ((ph) / scenarios.length) + (((ph / scenarios.length) - barH) / 2);
    const bufVal = s.buffer_months || 0;
    const barW   = (bufVal / maxBuf) * pw;
    const sev    = (s.severity || 'MODERATE').toUpperCase();
    const color  = sevColors[sev] || '#888';

    // Background track
    ctx.fillStyle = '#f5f5f5';
    ctx.fillRect(PAD.left, y, pw, barH);

    // Value bar
    ctx.fillStyle = color;
    ctx.fillRect(PAD.left, y, barW, barH);

    // Danger threshold line at 6 months
    const threshold6 = (6 / maxBuf) * pw;
    ctx.strokeStyle = '#111';
    ctx.lineWidth   = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(PAD.left + threshold6, PAD.top);
    ctx.lineTo(PAD.left + threshold6, H - PAD.bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    // Bar label (buffer months)
    ctx.fillStyle   = '#fff';
    ctx.font        = 'bold 9px Space Mono, monospace';
    ctx.textAlign   = 'left';
    ctx.textBaseline = 'middle';
    if (barW > 24) ctx.fillText(`${bufVal} mo.`, PAD.left + barW - 36, y + barH / 2);
    else {
      ctx.fillStyle = '#555';
      ctx.fillText(`${bufVal} mo.`, PAD.left + barW + 4, y + barH / 2);
    }

    // Scenario name (left label)
    ctx.fillStyle   = '#111';
    ctx.font        = '9px Space Mono, monospace';
    ctx.textAlign   = 'right';
    ctx.textBaseline = 'middle';
    const name = (s.name || 'Scenario').slice(0, 22);
    ctx.fillText(name, PAD.left - 6, y + barH / 2);

    // Survivable indicator
    ctx.fillStyle = s.survivable ? '#065f46' : '#991b1b';
    ctx.font      = 'bold 8px Space Mono, monospace';
    ctx.textAlign = 'right';
    ctx.fillText(s.survivable ? '✓' : '✗', PAD.left - 38, y + barH / 2);
  });

  // Axis label at bottom
  ctx.fillStyle    = '#888';
  ctx.font         = '8px Space Mono, monospace';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText('Buffer Months (RBI min: 6 months recommended)', PAD.left + pw / 2, H - 2);
}

// ════════════════════════════════════════════════════
