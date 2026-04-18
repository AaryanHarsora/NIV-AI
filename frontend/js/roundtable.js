// 9. LOCAL COMPUTATION FALLBACK
// ════════════════════════════════════════════════════
function computeLocalResults(inp) {
  const stateStampMap = {
    'Maharashtra': 0.05, 'Karnataka': 0.056, 'Delhi': 0.06, 'Tamil Nadu': 0.07,
    'Telangana': 0.06, 'Gujarat': 0.049, 'Rajasthan': 0.06, 'West Bengal': 0.06,
    'Uttar Pradesh': 0.07, 'Punjab': 0.06, 'Haryana': 0.07, 'Kerala': 0.08,
    'Andhra Pradesh': 0.05, 'Madhya Pradesh': 0.05
  };
  const gstRate   = (inp.property_type === 'under_construction') ? 0.05 : 0;
  const stampRate = stateStampMap[inp.state] || 0.05;
  const price = inp.property_price;
  const gst   = price * gstRate;
  const stamp = price * stampRate;
  const reg   = price * 0.01;
  const totalCost = price + gst + stamp + reg;

  const loanAmt = price - inp.down_payment;
  const r = (inp.annual_interest_rate / 100) / 12;
  const n = inp.tenure_years * 12;
  const emi = loanAmt > 0 ? (loanAmt * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1) : 0;
  const surplus = inp.monthly_income - inp.monthly_expenses - emi;
  const emiRatio = emi / inp.monthly_income;

  let riskScore = 0;
  if (emiRatio > 0.4) riskScore += 30;
  else if (emiRatio > 0.3) riskScore += 15;
  if (surplus < 0) riskScore += 25;
  if ((totalCost - price) / price > 0.15) riskScore += 15;
  if (behavioralAnswers?.[0]?.answer === 'buy_immediately') riskScore += 10;
  if (inp.down_payment / price < 0.2) riskScore += 10;
  riskScore = Math.min(riskScore, 100);

  const riskLabel    = riskScore >= 60 ? 'HIGH' : riskScore >= 35 ? 'MEDIUM' : 'LOW';
  const verdict      = riskLabel === 'HIGH' ? 'NO-GO' : 'GO';
  const confidence   = riskLabel === 'HIGH' ? 0.82 : riskLabel === 'MEDIUM' ? 0.71 : 0.88;
  const affordStatus = emiRatio < 0.3 ? 'AFFORDABLE' : emiRatio < 0.4 ? 'STRETCHED' : 'UNAFFORDABLE';

  const bufMonths = surplus > 0
    ? Math.floor(inp.total_savings / (Math.abs(surplus) + 1))
    : Math.max(0, Math.floor(inp.total_savings / (inp.monthly_expenses + emi)));

  const scenarios = [
    {
      name: 'Income Shock (−20%)',
      survivable: (inp.monthly_income * 0.8 - inp.monthly_expenses - emi) >= 0,
      buffer_months: bufMonths,
      severity: emiRatio > 0.4 ? 'CRITICAL' : 'MODERATE',
      description: `If income drops 20%, net change vs. current surplus would be ${fmt(Math.round(inp.monthly_income * -0.2))}.`
    },
    {
      name: 'Rate Hike (+200bps)',
      survivable: surplus > 0,
      buffer_months: 6,
      severity: riskLabel,
      description: `A 2% rate increase would raise EMI by ~${fmt(Math.round(loanAmt * 0.002 / 12))}.`
    },
    {
      name: 'Emergency Fund Test',
      survivable: inp.total_savings >= (inp.monthly_expenses + emi) * 6,
      buffer_months: Math.floor(inp.total_savings / Math.max(1, inp.monthly_expenses + emi)),
      severity: inp.total_savings < (inp.monthly_expenses + emi) * 3 ? 'CRITICAL' : 'MODERATE',
      description: `Savings cover ${Math.floor(inp.total_savings / Math.max(1, inp.monthly_expenses + emi))} months of combined expenses + EMI.`
    }
  ];

  const riskFactors = [
    { label: `EMI/Income ratio ${(emiRatio * 100).toFixed(1)}% (safe: <30%)`, triggered: emiRatio > 0.30 },
    { label: `Monthly surplus ${fmt(Math.round(surplus))}`, triggered: surplus < 0 },
    { label: `Down payment ${(inp.down_payment / price * 100).toFixed(1)}% (min: 20%)`, triggered: inp.down_payment / price < 0.2 },
    { label: `Hidden cost overhang ${((totalCost - price) / price * 100).toFixed(1)}% above base`, triggered: (totalCost - price) / price > 0.15 },
    { label: `Behavioral: ${behavioralAnswers?.[0]?.answer === 'buy_immediately' ? 'FOMO detected (+risk)' : 'Rational profile'}`, triggered: behavioralAnswers?.[0]?.answer === 'buy_immediately' }
  ];

  return {
    financial_reality: {
      emi: Math.round(emi),
      emi_to_income_ratio: emiRatio,
      monthly_surplus: Math.round(surplus),
      loan_amount: Math.round(loanAmt),
      affordability_status: affordStatus
    },
    hidden_costs: {
      base_price: price,
      gst: Math.round(gst),
      stamp_duty: Math.round(stamp),
      registration: Math.round(reg),
      total_cost: Math.round(totalCost)
    },
    scenarios,
    risk_assessment: {
      composite_score: riskScore,
      risk_label: riskLabel,
      factors: riskFactors
    },
    verdict: {
      decision: verdict,
      confidence,
      reasoning: `Deterministic engine result: EMI/income ${(emiRatio * 100).toFixed(1)}% — ${emiRatio > 0.4 ? 'EXCEEDS RBI 40% advisory' : emiRatio > 0.3 ? 'within cautionary 30–40% zone' : 'within safe zone <30%'}. Monthly surplus post-EMI: ${fmt(Math.round(surplus))}. ${surplus < 0 ? 'Critical: negative surplus — no discretionary buffer.' : 'Positive surplus provides marginal safety.'} ${behavioralAnswers?.[0]?.answer === 'buy_immediately' ? 'FOMO behavioral bias detected — risk premium applied.' : 'Rational behavioral profile confirmed.'} ${verdict === 'GO' ? 'Proceed cautiously. Maintain 6-month emergency reserve before committing.' : 'Avoid commitment. Improve financial position first.'}`
    },
    session_id
  };
}

// ════════════════════════════════════════════════════
// 10. FORCE-DIRECTED INTERACTION GRAPH
// ════════════════════════════════════════════════════
const AGENT_COLORS = {
  math: '#60a5fa',
  bias: '#fbbf24',
  reg:  '#34d399',
  risk: '#f87171',
  sys:  '#b45309'
};
const AGENT_LABELS = {
  math: 'MATH', bias: 'BIAS', reg: 'REG', risk: 'RISK', sys: 'SYS'
};

let forceNodes = [];
let forceEdges = [];
let interactionCounts = {};

function initForceGraph() {
  const canvas = document.getElementById('force-canvas');
  if (!canvas) return;

  // Set canvas pixel dimensions
  const W = canvas.offsetWidth || 400;
  const H = 280;
  canvas.width  = W;
  canvas.height = H;

  const cx = W / 2, cy = H / 2;

  forceNodes = [
    { id: 'sys',  x: cx,        y: cy - 80,  vx: 0, vy: 0, active: true,  done: false, r: 20 },
    { id: 'math', x: cx - 100,  y: cy + 40,  vx: 0, vy: 0, active: false, done: false, r: 18 },
    { id: 'bias', x: cx + 100,  y: cy + 40,  vx: 0, vy: 0, active: false, done: false, r: 18 },
    { id: 'reg',  x: cx - 50,   y: cy + 100, vx: 0, vy: 0, active: false, done: false, r: 18 },
    { id: 'risk', x: cx + 50,   y: cy + 100, vx: 0, vy: 0, active: false, done: false, r: 18 },
  ];
  forceEdges = [];
  interactionCounts = {};

  document.getElementById('interaction-ledger-body').innerHTML =
    '<div style="color:#444;font-size:0.58rem">Waiting for agent communication...</div>';

  stopForceGraph();
  drawForceGraph();
}

function addForceEdge(fromId, toId) {
  const key = [fromId, toId].sort().join('-');
  interactionCounts[key] = (interactionCounts[key] || 0) + 1;

  const existing = forceEdges.find(e => e.key === key);
  if (existing) {
    existing.weight = interactionCounts[key];
  } else {
    forceEdges.push({ key, from: fromId, to: toId, weight: 1 });
    updateInteractionLedger();
  }
}

function updateInteractionLedger() {
  const body = document.getElementById('interaction-ledger-body');
  const sorted = Object.entries(interactionCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);

  if (sorted.length === 0) return;

  body.innerHTML = sorted.map(([key, count]) => {
    const [a, b] = key.split('-');
    return `<div class="ledger-entry">
      <span class="ledger-from">${AGENT_LABELS[a] || a}</span>
      <span class="ledger-arrow">↔</span>
      <span class="ledger-to">${AGENT_LABELS[b] || b}</span>
      <span class="ledger-count">×${count}</span>
    </div>`;
  }).join('');
}

function drawForceGraph() {
  const canvas = document.getElementById('force-canvas');
  if (!canvas || currentState !== STATES.LOADING) { forceAnimFrame = null; return; }

  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;

  // Physics tick
  const K_REPEL  = 3000;
  const K_SPRING = 0.03;
  const K_DAMP   = 0.85;
  const BORDER   = 40;

  for (let i = 0; i < forceNodes.length; i++) {
    let fx = 0, fy = 0;
    const ni = forceNodes[i];

    // Repulsion from other nodes
    for (let j = 0; j < forceNodes.length; j++) {
      if (i === j) continue;
      const nj = forceNodes[j];
      const dx = ni.x - nj.x, dy = ni.y - nj.y;
      const dist2 = Math.max(dx * dx + dy * dy, 100);
      const dist  = Math.sqrt(dist2);
      fx += K_REPEL * dx / (dist2 * dist) * dist;
      fy += K_REPEL * dy / (dist2 * dist) * dist;
    }

    // Spring attraction from edges
    for (const edge of forceEdges) {
      let partner = null;
      if (edge.from === ni.id) {
        partner = forceNodes.find(n => n.id === edge.to);
      } else if (edge.to === ni.id) {
        partner = forceNodes.find(n => n.id === edge.from);
      }
      if (!partner) continue;
      const dx = partner.x - ni.x, dy = partner.y - ni.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const targetDist = 120 - edge.weight * 5;
      const force = K_SPRING * (dist - targetDist);
      fx += force * dx / Math.max(dist, 1);
      fy += force * dy / Math.max(dist, 1);
    }

    // Center gravity
    fx += (W / 2 - ni.x) * 0.005;
    fy += (H / 2 - ni.y) * 0.005;

    ni.vx = (ni.vx + fx) * K_DAMP;
    ni.vy = (ni.vy + fy) * K_DAMP;
    ni.x  = Math.max(BORDER, Math.min(W - BORDER, ni.x + ni.vx));
    ni.y  = Math.max(BORDER, Math.min(H - BORDER, ni.y + ni.vy));
  }

  // Render
  ctx.clearRect(0, 0, W, H);

  // Draw grid-like background pattern
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 30) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 0; y < H; y += 30) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

  // Draw edges
  for (const edge of forceEdges) {
    const nFrom = forceNodes.find(n => n.id === edge.from);
    const nTo   = forceNodes.find(n => n.id === edge.to);
    if (!nFrom || !nTo) continue;

    const weight = Math.min(edge.weight, 5);
    ctx.beginPath();
    ctx.moveTo(nFrom.x, nFrom.y);
    ctx.lineTo(nTo.x, nTo.y);
    ctx.strokeStyle = `rgba(180,83,9,${0.15 + weight * 0.12})`;
    ctx.lineWidth = weight;
    ctx.stroke();

    // Edge weight label
    const mx = (nFrom.x + nTo.x) / 2;
    const my = (nFrom.y + nTo.y) / 2;
    ctx.fillStyle = 'rgba(180,83,9,0.8)';
    ctx.font = '9px Space Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`×${edge.weight}`, mx, my - 4);
  }

  // Draw nodes
  for (const node of forceNodes) {
    const color = AGENT_COLORS[node.id] || '#888';
    const isActive = node.active;
    const isDone   = node.done;

    // Glow / pulse for active node
    if (isActive && !isDone) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r + 8, 0, Math.PI * 2);
      ctx.fillStyle = color.replace(')', ',0.15)').replace('rgb(', 'rgba(');
      ctx.fill();
    }

    // Node fill
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
    ctx.fillStyle = isDone ? '#22c55e' : isActive ? color : 'rgba(255,255,255,0.08)';
    ctx.fill();

    // Node border
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
    ctx.strokeStyle = isDone ? '#22c55e' : isActive ? color : 'rgba(255,255,255,0.2)';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Label
    ctx.fillStyle = isDone ? '#fff' : isActive ? '#fff' : 'rgba(255,255,255,0.3)';
    ctx.font = `bold 9px Space Mono, monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(AGENT_LABELS[node.id] || node.id.toUpperCase(), node.x, node.y);
  }

  forceAnimFrame = requestAnimationFrame(drawForceGraph);
}

function stopForceGraph() {
  if (forceAnimFrame) {
    cancelAnimationFrame(forceAnimFrame);
    forceAnimFrame = null;
  }
}

function setForceNodeActive(agentId) {
  const node = forceNodes.find(n => n.id === agentId);
  if (node) { node.active = true; }

  // Add edge from sys to this agent (sys always sends work)
  if (agentId !== 'sys') {
    addForceEdge('sys', agentId);
    // Also add edges between sequential agents for roundtable logic
    const agentOrder = ['math', 'bias', 'reg', 'risk'];
    const idx = agentOrder.indexOf(agentId);
    if (idx > 0) {
      addForceEdge(agentOrder[idx - 1], agentId);
    }
  }
}

function setForceNodeDone(agentId) {
  const node = forceNodes.find(n => n.id === agentId);
  if (node) { node.done = true; }
}

// ════════════════════════════════════════════════════
// 11. WEBSOCKET ROUNDTABLE
// ════════════════════════════════════════════════════
function startRoundtable() {
  const termBody = document.getElementById('terminal-body');
  termBody.innerHTML = '<span class="cursor-blink" id="cursor"></span>';
  ['math','bias','reg','risk'].forEach(a => {
    document.getElementById(`ac-${a}`).className = 'agent-card';
    document.getElementById(`as-${a}`).textContent = 'Standby';
  });

  setWsStatus('connecting', 'Connecting to /roundtable/' + session_id);
  logDebug('WS', `/roundtable/${session_id}`, 'CONNECTING');

  const wsUrl = `${WS_BASE}/roundtable/${session_id}?token=${AUTH_TOKEN}`;
  let wsOpen  = false;
  let wsTimeout = null;

  try {
    const ws = new WebSocket(wsUrl);
    wsConnection = ws;

    wsTimeout = setTimeout(() => {
      if (!wsOpen) { ws.close(); runSimulatedRoundtable(); }
    }, 3000);

    ws.onopen = () => {
      wsOpen = true;
      clearTimeout(wsTimeout);
      logDebug('WS', `/roundtable/${session_id}`, 'CONNECTED', true);
      setWsStatus('connected', 'Stream connected — Round 1 active');
    };
    ws.onmessage = (evt) => {
      try { handleWsMessage(JSON.parse(evt.data)); }
      catch { appendLog('sys', '[STREAM]', evt.data); }
    };
    ws.onerror = () => {
      if (!wsOpen) { clearTimeout(wsTimeout); logDebug('WS', '/roundtable', 'ERROR', false); runSimulatedRoundtable(); }
    };
    ws.onclose = (e) => {
      if (e.code !== 1000 && currentState === STATES.LOADING)
        setWsStatus('error', 'Stream closed — ' + (e.reason || 'ended'));
    };
  } catch (err) {
    clearTimeout(wsTimeout);
    runSimulatedRoundtable();
  }
}

function handleWsMessage(msg) {
  const agent = msg.agent || '[AGENT]';
  const text  = msg.message || JSON.stringify(msg);
  const round = msg.round;
  if (round) {
    document.getElementById('terminal-round').textContent = `ROUND ${round}`;
    document.getElementById('graph-round-label').textContent = `ROUND ${round}`;
  }

  const agentMap = {
    'math': 'math', 'MATH': 'math', 'bias': 'bias', 'BIAS': 'bias',
    'reg':  'reg',  'REG':  'reg',  'regulatory': 'reg',
    'risk': 'risk', 'RISK': 'risk', 'system': 'sys', 'SYSTEM': 'sys'
  };
  const agentKey = agentMap[agent.toLowerCase().replace(/[\[\]]/g, '')] || 'sys';

  appendLog(agentKey, `[${agent.toUpperCase().replace(/[\[\]]/g, '')}]`, text);
  activateAgentCard(agentKey);
  setForceNodeActive(agentKey);

  if (msg.type === 'verdict' || msg.final) {
    if (msg.results) backendResults = msg.results;
    finishRoundtable();
  }
}

function setWsStatus(state, label) {
  const dot = document.getElementById('ws-dot');
  const lbl = document.getElementById('ws-label');
  dot.className = 'ws-dot ' + (state === 'connected' ? 'connected' : state === 'error' ? 'error' : '');
  lbl.textContent = label;
}

function appendLog(agentCls, agentLabel, message) {
  const termBody = document.getElementById('terminal-body');
  const cursor   = document.getElementById('cursor');
  const now = new Date().toTimeString().slice(0,8);
  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `
    <span class="log-ts">${now}</span>
    <span class="log-agent ${agentCls}">${agentLabel}</span>
    <span class="log-msg">${message}</span>
  `;
  termBody.insertBefore(line, cursor);
  termBody.scrollTop = termBody.scrollHeight;
}

function activateAgentCard(agentKey) {
  const map = { math: 'math', bias: 'bias', reg: 'reg', risk: 'risk' };
  const key = map[agentKey];
  if (!key) return;
  ['math','bias','reg','risk'].forEach(k => {
    const card = document.getElementById(`ac-${k}`);
    if (k === key && !card.classList.contains('done')) {
      card.className = 'agent-card active';
      document.getElementById(`as-${k}`).textContent = 'Processing...';
    }
  });
}

function completeAgentCard(key, statusText) {
  const card = document.getElementById(`ac-${key}`);
  if (!card) return;
  card.className = 'agent-card done';
  document.getElementById(`as-${key}`).textContent = statusText || '✓ Done';
  setForceNodeDone(key);
}

// ════════════════════════════════════════════════════
// 12. SIMULATED ROUNDTABLE (offline fallback)
// ════════════════════════════════════════════════════
function runSimulatedRoundtable() {
  setWsStatus('connecting', 'Backend unavailable — local engine active');
  logDebug('WS', '/roundtable', 'LOCAL MODE', false);
  document.getElementById('graph-round-label').textContent = 'LOCAL';

  const r   = backendResults;
  const fr  = r?.financial_reality || {};
  const hc  = r?.hidden_costs || {};
  const ra  = r?.risk_assessment || {};
  const v   = r?.verdict || {};
  const inp = userInput || {};

  const logs = [
    { a: 'sys',  l: '[SYSTEM]',     m: `Session ${session_id} — State: ${inp.state || '—'} | Price: ${fmt(inp.property_price)} | Type: ${inp.property_type || '—'}` },
    { a: 'math', l: '[MATH-AGENT]', m: 'EMI computation engine initialized...' },
    { a: 'math', l: '[MATH-AGENT]', m: `Loan: ${fmt(fr.loan_amount)} | Tenure: ${inp.tenure_years}y | Rate: ${inp.annual_interest_rate}% p.a.` },
    { a: 'math', l: '[MATH-AGENT]', m: `Monthly EMI: ${fmt(fr.emi)} | EMI/Income: ${(fr.emi_to_income_ratio * 100).toFixed(1)}%` },
    { a: 'math', l: '[MATH-AGENT]', m: `Surplus post-EMI: ${fmt(fr.monthly_surplus)} | Status: ${fr.affordability_status}` },
    { a: 'bias', l: '[BIAS-AGENT]', m: `Behavioral profile loaded: ${behavioralAnswers?.[0]?.answer === 'buy_immediately' ? 'FOMO' : 'RATIONAL'} pattern detected` },
    { a: 'bias', l: '[BIAS-AGENT]', m: behavioralAnswers?.[0]?.answer === 'buy_immediately' ? 'WARNING: FOMO signal active — behavioral risk premium +10 pts' : 'Rational signal confirmed — minimal impulsivity adjustment' },
    { a: 'reg',  l: '[REG-AGENT]',  m: `RBI 40% EMI compliance check: ${(fr.emi_to_income_ratio * 100).toFixed(1)}% → ${fr.emi_to_income_ratio > 0.4 ? '⚠ BREACH' : '✓ CLEAR'}` },
    { a: 'reg',  l: '[REG-AGENT]',  m: `RERA cost breakdown: GST ${fmt(hc.gst)} | Stamp ${fmt(hc.stamp_duty)} | Reg ${fmt(hc.registration)}` },
    { a: 'reg',  l: '[REG-AGENT]',  m: `Total acquisition cost: ${fmt(hc.total_cost)} | Overhang: ${((hc.total_cost - hc.base_price) / hc.base_price * 100).toFixed(1)}% above base` },
    { a: 'risk', l: '[RISK-AGENT]', m: 'Running 3-scenario stress model: Income Shock | Rate Hike | Emergency Fund' },
    { a: 'risk', l: '[RISK-AGENT]', m: `Composite risk score: ${ra.composite_score}/100 | Risk level: ${ra.risk_label}` },
    { a: 'risk', l: '[RISK-AGENT]', m: `Factor analysis — ${ra.factors?.filter(f => f.triggered).length || 0} risk triggers active` },
    { a: 'sys',  l: '[SYSTEM]',     m: `▶ VERDICT: ${v.decision} | Confidence: ${((v.confidence || 0) * 100).toFixed(0)}% | Engine v2.0` },
  ];

  const agentPhases = {
    math: { start: 1, end: 4 },
    bias: { start: 5, end: 6 },
    reg:  { start: 7, end: 9 },
    risk: { start: 10, end: 12 }
  };

  let round = 1;
  const delay = 520;

  logs.forEach((log, i) => {
    setTimeout(() => {
      if (i === 5) {
        round = 2;
        document.getElementById('terminal-round').textContent = `ROUND ${round}`;
        document.getElementById('graph-round-label').textContent = `ROUND ${round}`;
      }
      if (i === 10) {
        round = 3;
        document.getElementById('terminal-round').textContent = `ROUND ${round}`;
        document.getElementById('graph-round-label').textContent = `ROUND ${round}`;
      }

      Object.entries(agentPhases).forEach(([key, phase]) => {
        const card = document.getElementById(`ac-${key}`);
        if (i === phase.start) {
          card.className = 'agent-card active';
          document.getElementById(`as-${key}`).textContent = 'Processing...';
          setForceNodeActive(key);
        }
        if (i === phase.end + 1) completeAgentCard(key);
      });

      appendLog(log.a, log.l, log.m);
      if (log.a !== 'sys') setForceNodeActive(log.a);

      if (i === logs.length - 1) {
        completeAgentCard('risk');
        setWsStatus('connected', 'Analysis complete — rendering verdict');
        setTimeout(finishRoundtable, 700);
      }
    }, i * delay);
  });
}

function finishRoundtable() {
  if (currentState !== STATES.LOADING) return;
  stopForceGraph();
  transitionTo(STATES.DASHBOARD);
  renderVerdict();
}

// ════════════════════════════════════════════════════
// 15. CONVERSATION (POST /conversation)
// ════════════════════════════════════════════════════
let convHistory = [];

async function sendConversation() {
  const input = document.getElementById('conv-input');
  const sendBtn = document.getElementById('conv-send-btn');
  const msg = input.value.trim();
  if (!msg || !session_id) return;

  // Disable while processing
  input.value = '';
  sendBtn.disabled = true;
  sendBtn.textContent = '⟳';

  // Show user message
  appendConvMessage('user', msg);

  // POST /conversation
  const payload = {
    message: msg,
    context: {
      results: backendResults,
      input: userInput,
      behavioral: behavioralAnswers
    },
    history: convHistory
  };

  let aiReply = '';
  try {
    const data = await apiPost(`/conversation/${session_id}`, payload);
    aiReply = data.response || data.message || data.reply || 'Analysis received.';
    convHistory.push({ role: 'user', content: msg });
    convHistory.push({ role: 'assistant', content: aiReply });
  } catch (err) {
    // Offline: generate local AI response
    aiReply = generateLocalConvResponse(msg);
  }

  appendConvMessage('ai', aiReply);
  sendBtn.disabled = false;
  sendBtn.textContent = '⟶ Ask';
}

function appendConvMessage(role, text) {
  const container = document.getElementById('conv-messages');
  const div = document.createElement('div');
  div.className = `conv-msg ${role}`;
  if (role === 'ai') {
    div.innerHTML = `<span class="conv-sender">NIV AI</span><span class="conv-bubble">${text}</span>`;
  } else {
    div.innerHTML = `<span class="conv-bubble">${text}</span>`;
  }
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function generateLocalConvResponse(question) {
  const fr  = backendResults?.financial_reality || {};
  const ra  = backendResults?.risk_assessment   || {};
  const hc  = backendResults?.hidden_costs      || {};
  const v   = backendResults?.verdict           || {};
  const inp = userInput || {};

  const q = question.toLowerCase();

  if (q.includes('emi') || q.includes('monthly')) {
    return `Your monthly EMI is ${fmt(fr.emi)}, representing ${((fr.emi_to_income_ratio || 0) * 100).toFixed(1)}% of your income. RBI advisory is <40%. Your monthly surplus post-EMI and expenses is ${fmt(fr.monthly_surplus)}.`;
  }
  if (q.includes('down') || q.includes('payment')) {
    const pct = ((inp.down_payment || 0) / (inp.property_price || 1) * 100).toFixed(1);
    return `Your down payment is ${fmt(inp.down_payment)} (${pct}% of property value). A higher down payment reduces loan amount, EMI, and risk score. RBI recommends minimum 20% — ${parseFloat(pct) >= 20 ? 'you meet this threshold.' : 'you are below this threshold.'}`;
  }
  if (q.includes('risk') || q.includes('score')) {
    const triggered = ra.factors?.filter(f => f.triggered).length || 0;
    return `Composite risk score: ${ra.composite_score}/100 (${ra.risk_label} RISK). ${triggered} of ${ra.factors?.length || 0} risk factors triggered. ${ra.risk_label === 'HIGH' ? 'High risk — address at least 2 factors before proceeding.' : ra.risk_label === 'MEDIUM' ? 'Moderate risk — proceed with caution, build emergency reserve.' : 'Low risk — financial parameters are within acceptable bounds.'}`;
  }
  if (q.includes('hidden') || q.includes('cost') || q.includes('gst') || q.includes('stamp')) {
    return `True acquisition cost: ${fmt(hc.total_cost)} vs. base price ${fmt(hc.base_price)}. Breakdown: GST ${fmt(hc.gst)} + Stamp Duty ${fmt(hc.stamp_duty)} + Registration ${fmt(hc.registration)} = ${fmt((hc.gst || 0) + (hc.stamp_duty || 0) + (hc.registration || 0))} in additional costs (${(((hc.total_cost - hc.base_price) / hc.base_price) * 100).toFixed(1)}% above base).`;
  }
  if (q.includes('increase') && q.includes('down')) {
    const newDown   = (inp.down_payment || 0) * 1.2;
    const newLoan   = (inp.property_price || 0) - newDown;
    const r         = ((inp.annual_interest_rate || 8.75) / 100) / 12;
    const n         = (inp.tenure_years || 20) * 12;
    const newEmi    = newLoan > 0 ? (newLoan * r * Math.pow(1+r,n)) / (Math.pow(1+r,n) - 1) : 0;
    const newRatio  = newEmi / (inp.monthly_income || 1);
    return `If down payment increases by 20% to ${fmt(Math.round(newDown))}, the new EMI would be ${fmt(Math.round(newEmi))} (${(newRatio * 100).toFixed(1)}% of income). This would ${newRatio < fr.emi_to_income_ratio ? 'reduce financial pressure' : 'not significantly change the ratio'}.`;
  }
  if (q.includes('verdict') || q.includes('decision') || q.includes('go') || q.includes('buy')) {
    return `Verdict: ${v.decision} with ${((v.confidence || 0) * 100).toFixed(0)}% confidence. ${v.reasoning?.slice(0, 180) || 'See full analysis above.'}`;
  }
  if (q.includes('savings') || q.includes('emergency')) {
    const monthsBuffer = Math.floor((inp.total_savings || 0) / Math.max(1, (inp.monthly_expenses || 0) + (fr.emi || 0)));
    return `Total savings: ${fmt(inp.total_savings)}. This covers ${monthsBuffer} months of combined expenses + EMI. ${monthsBuffer >= 6 ? '✓ Meets the 6-month emergency reserve benchmark.' : '⚠ Below the recommended 6-month emergency reserve.'}`;
  }

  return `Based on your profile: EMI is ${fmt(fr.emi)} (${((fr.emi_to_income_ratio || 0) * 100).toFixed(1)}% of income), risk score ${ra.composite_score}/100, total cost ${fmt(hc.total_cost)}. Verdict: ${v.decision}. Ask me about EMI, hidden costs, risk factors, scenarios, or down payment strategies.`;
}

// ════════════════════════════════════════════════════
// 16. REPORT DOWNLOAD
// ════════════════════════════════════════════════════
async function downloadReport() {
  const btn = document.getElementById('btn-download-report');
  btn.classList.add('loading-report');
  btn.textContent = '⟳ Generating...';
  logDebug('GET', `/report/${session_id}`, 'pending...');

  try {
    const res = await fetch(`${API_BASE}/report/${session_id}`, {
      method: 'GET',
      headers: authHeaders()
    });
    if (!res.ok) throw new Error('Report endpoint returned ' + res.status);
    logDebug('GET', `/report/${session_id}`, `${res.status} OK`, true);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `NIV-AI-Report-${session_id}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
    btn.classList.remove('loading-report');
    btn.textContent = '✓ Downloaded';
  } catch (err) {
    logDebug('GET', `/report/${session_id}`, 'UNAVAILABLE', false);
    btn.classList.remove('loading-report');
    btn.textContent = '↓ Download Report';
    showToast('Report download unavailable — backend offline');
  }
}

// ════════════════════════════════════════════════════
