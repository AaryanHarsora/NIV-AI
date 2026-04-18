// 1. CONFIGURATION
// ════════════════════════════════════════════════════
const API_BASE  = 'http://localhost:8080';
const WS_BASE   = 'ws://localhost:8080';
const AUTH_TOKEN = 'niv-placeholder-token-2025';

const STATES = { LOGIN: 0, BEHAVIORAL: 1, INPUT: 2, LOADING: 3, DASHBOARD: 4 };
const STATE_LABELS = {
  0: 'SECURE LOGIN',
  1: 'BEHAVIORAL PROFILING',
  2: 'INPUT ENGINE',
  3: 'AGENT ROUNDTABLE',
  4: 'VERDICT DASHBOARD'
};

// ════════════════════════════════════════════════════
// 2. GLOBAL STATE
// ════════════════════════════════════════════════════
let currentState     = STATES.LOGIN;
let stateHistory     = [];
let session_id       = null;
let behavioralAnswers = null;
let userInput        = null;
let backendResults   = null;
let wsConnection     = null;
let isSubmitting     = false;
let forceAnimFrame   = null;
let debugOpen        = false;

// ════════════════════════════════════════════════════
// 3. UTILITIES
// ════════════════════════════════════════════════════
function fmt(n) {
  if (n === undefined || n === null || n === '') return '—';
  const num = parseFloat(n);
  if (isNaN(num)) return String(n);
  return '₹' + Math.round(num).toLocaleString('en-IN');
}
function showToast(msg, duration = 3800) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}
function showLoading(msg = 'Processing', sub = 'Please wait...') {
  document.getElementById('loading-msg').textContent = msg;
  document.getElementById('loading-sub').textContent = sub;
  document.getElementById('loading-overlay').classList.add('show');
}
function hideLoading() {
  document.getElementById('loading-overlay').classList.remove('show');
}
function authHeaders() {
  return { 'Content-Type': 'application/json', 'Authorization': `Bearer ${AUTH_TOKEN}` };
}

// ════════════════════════════════════════════════════
// 4. DEBUG PANEL
// ════════════════════════════════════════════════════
function toggleDebug() {
  debugOpen = !debugOpen;
  document.getElementById('debug-panel').classList.toggle('open', debugOpen);
}
function clearDebug() {
  document.getElementById('debug-log').innerHTML = '<div class="debug-entry" style="color:#333">Log cleared</div>';
}
function logDebug(method, path, status, ok = true) {
  const log = document.getElementById('debug-log');
  const ts = new Date().toTimeString().slice(0,8);
  const entry = document.createElement('div');
  entry.className = 'debug-entry';
  entry.innerHTML = `
    <span class="d-method">${method}</span>
    <span class="d-path">${path}</span>
    <span class="d-status ${ok ? 'ok' : 'err'}">${status}</span>
    <span class="d-ts">${ts}</span>
  `;
  // Remove placeholder
  const placeholder = log.querySelector('[style*="color:#333"]');
  if (placeholder) placeholder.remove();
  log.insertBefore(entry, log.firstChild);
}

// ════════════════════════════════════════════════════
// 5. STATE MACHINE
// ════════════════════════════════════════════════════
function transitionTo(newState) {
  if (newState !== currentState) stateHistory.push(currentState);
  currentState = newState;

  
  const statePageMap = {
    0: 'index.html',
    1: 'onboarding.html',
    2: 'onboarding.html',
    3: 'dashboard.html',
    4: 'dashboard.html'
  };
  const targetPage = statePageMap[newState];
  let currentPage = window.location.pathname.split('/').pop() || 'index.html';
  if (currentPage === '') currentPage = 'index.html';
  
  if (targetPage && targetPage !== currentPage) {
    sessionStorage.setItem('target_state', newState);
    window.location.href = targetPage;
    return;
  }
  document.querySelectorAll('.state').forEach(el => el.classList.remove('active'));
  const targetEl = document.getElementById(`state-${newState}`);
  if (!targetEl) return;

  document.getElementById(`state-${newState}`).classList.add('active');
  document.getElementById('state-label').textContent = STATE_LABELS[newState] || 'UNKNOWN';

  renderStepper(newState);

  document.getElementById('btn-back').disabled = (stateHistory.length === 0 || newState === STATES.LOGIN || newState === STATES.LOADING);
  document.getElementById('btn-reset').disabled = (newState === STATES.LOGIN);

  const badge = document.getElementById('session-badge');
  if (session_id) {
    badge.textContent = `SID: ${session_id.slice(0,8)}...`;
    badge.classList.add('visible');
  } else {
    badge.classList.remove('visible');
  }

  // Start/stop force graph animation
  if (newState === STATES.LOADING) {
    initForceGraph();
  } else {
    stopForceGraph();
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function goBack() {
  if (stateHistory.length === 0) return;
  if (wsConnection) { wsConnection.close(); wsConnection = null; }
  stopForceGraph();
  const prev = stateHistory.pop();
  currentState = prev;
  
  const statePageMap = {
    0: 'index.html',
    1: 'onboarding.html',
    2: 'onboarding.html',
    3: 'dashboard.html',
    4: 'dashboard.html'
  };
  const targetPage = statePageMap[prev];
  let currentPage = window.location.pathname.split('/').pop() || 'index.html';
  if (currentPage === '') currentPage = 'index.html';
  
  if (targetPage && targetPage !== currentPage) {
    sessionStorage.setItem('target_state', prev);
    window.location.href = targetPage;
    return;
  }
  document.querySelectorAll('.state').forEach(el => el.classList.remove('active'));
  const targetEl = document.getElementById(`state-${prev}`);
  if (!targetEl) return;

  document.getElementById(`state-${prev}`).classList.add('active');
  document.getElementById('state-label').textContent = STATE_LABELS[prev] || 'UNKNOWN';
  renderStepper(prev);
  document.getElementById('btn-back').disabled = (stateHistory.length === 0 || prev === STATES.LOGIN || prev === STATES.LOADING);
  document.getElementById('btn-reset').disabled = (prev === STATES.LOGIN);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetSystem() {
  if (wsConnection) { wsConnection.close(); wsConnection = null; }
  stopForceGraph();
  session_id = null;
  behavioralAnswers = null;
  userInput = null;
  backendResults = null;
  isSubmitting = false;
  stateHistory = [];
  ['f-income','f-expenses','f-savings','f-price','f-down','f-tenure','f-rate','f-age'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  ['f-state','f-ptype'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  document.getElementById('session-badge').classList.remove('visible');
  hideLoading();
  transitionTo(STATES.LOGIN);
}

// ════════════════════════════════════════════════════
// 6. STEPPER
// ════════════════════════════════════════════════════
const STEP_DEFS = [
  { label: 'Login' }, { label: 'Behavior' }, { label: 'Input' }, { label: 'Analysis' }, { label: 'Verdict' }
];

function renderStepper(activeState) {
  [1, 2, 3].forEach(stateNum => {
    const el = document.getElementById(`stepper-${stateNum}`);
    if (!el) return;
    let html = '<div class="stepper">';
    STEP_DEFS.forEach((step, i) => {
      const isDone = i < activeState;
      const isCurrent = i === activeState;
      html += `<div class="step ${isDone ? 'done' : ''} ${isCurrent ? 'current' : ''}">
        <div class="step-num">${isDone ? '✓' : i + 1}</div>
      </div>`;
      if (i < STEP_DEFS.length - 1) html += `<div class="step-line ${isDone ? 'done' : ''}"></div>`;
    });
    html += '</div>';
    el.innerHTML = html;
  });
}

// ════════════════════════════════════════════════════
// 7. API LAYER
// ════════════════════════════════════════════════════
async function apiPost(path, body) {
  logDebug('POST', path, 'pending...');
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      const errText = await res.text().catch(() => 'Unknown');
      logDebug('POST', path, `${res.status} ERR`, false);
      throw new Error(`API ${path} failed (${res.status}): ${errText}`);
    }
    logDebug('POST', path, `${res.status} OK`, true);
    return res.json();
  } catch (err) {
    logDebug('POST', path, 'OFFLINE', false);
    throw err;
  }
}

async function apiGet(path) {
  logDebug('GET', path, 'pending...');
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'GET',
      headers: authHeaders()
    });
    if (!res.ok) {
      logDebug('GET', path, `${res.status} ERR`, false);
      throw new Error(`API GET ${path} failed (${res.status})`);
    }
    logDebug('GET', path, `${res.status} OK`, true);
    return res.json();
  } catch (err) {
    logDebug('GET', path, 'OFFLINE', false);
    throw err;
  }
}

// ════════════════════════════════════════════════════
// 17. SESSION RESTORE
// ════════════════════════════════════════════════════
async function tryRestoreSession() {
  const saved = sessionStorage.getItem('niv_session_id');
  if (!saved) return;
  try {
    const data = await apiGet(`/session/${saved}`);
    if (data && data.session_id) {
      session_id = data.session_id;
      if (data.results)          backendResults    = data.results;
      if (data.user_input)       userInput         = data.user_input;
      if (data.behavioral)       behavioralAnswers = data.behavioral;
      if (data.results) {
        transitionTo(STATES.DASHBOARD);
        renderVerdict();
      }
    }
  } catch (err) {
    console.warn('Session restore failed:', err.message);
  }
}

// ════════════════════════════════════════════════════
// 18. BOOT
// ════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  
  const targetState = sessionStorage.getItem('target_state');
  if (targetState !== null) {
      sessionStorage.removeItem('target_state');
      transitionTo(parseInt(targetState));
  } else {
      let currentPage = window.location.pathname.split('/').pop() || 'index.html';
      if (currentPage === '' || currentPage === 'index.html') transitionTo(STATES.LOGIN);
      else if (currentPage === 'onboarding.html') transitionTo(STATES.BEHAVIORAL);
      else if (currentPage === 'dashboard.html') transitionTo(STATES.DASHBOARD);
  }


  // Save session_id to sessionStorage on state changes
  const origTransition = transitionTo;
  // Persist session on analysis complete
  document.addEventListener('visibilitychange', () => {
    if (session_id) sessionStorage.setItem('niv_session_id', session_id);
  });

  // Keyboard shortcut: Ctrl+D to toggle debug
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.key === 'd') { e.preventDefault(); toggleDebug(); }
  });

  // Resize charts on window resize when dashboard is visible
  window.addEventListener('resize', () => {
    if (currentState === STATES.DASHBOARD && backendResults) {
      clearTimeout(window._resizeTimer);
      window._resizeTimer = setTimeout(renderAllCharts, 300);
    }
    if (currentState === STATES.LOADING) {
      const canvas = document.getElementById('force-canvas');
      if (canvas) {
        canvas.width = canvas.offsetWidth;
        canvas.height = 280;
      }
    }
  });
});
