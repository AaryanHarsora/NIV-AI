/**
 * chat.js — NIV AI chat interface
 *
 * Handles:
 *   - Chat session lifecycle (start, message, reset)
 *   - WebSocket connection for live roundtable
 *   - UI state management (progress, status steps, roundtable feed)
 *   - Report download trigger
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let sessionId = null;
let ws = null;
let isWaiting = false;   // true while waiting for API response
let analysisStarted = false;

// ─── Utilities ────────────────────────────────────────────────────────────────

function showToast(msg, duration = 3500) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), duration);
}

function setStateLabel(text) {
    const el = document.getElementById('state-label');
    if (el) el.textContent = text;
}

function showLoading(msg = 'Processing', sub = 'Please wait...') {
    document.getElementById('loading-msg').textContent = msg;
    document.getElementById('loading-sub').textContent = sub;
    document.getElementById('loading-overlay').classList.add('show');
}

function hideLoading() {
    document.getElementById('loading-overlay').classList.remove('show');
}

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

function scrollToBottom() {
    const msgs = document.getElementById('messages');
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

function formatTime() {
    return new Date().toLocaleTimeString('en-IN', {
        hour: '2-digit', minute: '2-digit'
    });
}

// ─── Session start ─────────────────────────────────────────────────────────────

async function startChat() {
    showLoading('Connecting to NIV AI', 'Initializing session...');

    try {
        const res = await fetch(`${API_BASE}/chat/start`, { method: 'POST' });
        const data = await res.json();

        if (!data.success) throw new Error(data.message || 'Failed to start session');

        sessionId = data.data.session_id;

        // Update session badge
        const badge = document.getElementById('session-badge');
        badge.textContent = `SID: ${sessionId.slice(0, 8).toUpperCase()}`;
        badge.classList.remove('hidden');

        // Show chat UI, hide splash
        document.getElementById('welcome-splash').style.display = 'none';
        document.getElementById('messages').classList.remove('hidden');
        document.getElementById('input-row').classList.remove('hidden');
        document.getElementById('input-hint').classList.remove('hidden');
        document.getElementById('progress-wrap').classList.remove('hidden');

        // Render opening message
        appendMessage('assistant', data.data.opening_message);
        setStateLabel('CHAT — COLLECTING DATA');

        document.getElementById('chat-input').focus();

    } catch (err) {
        showToast(`Connection failed: ${err.message}`);
        console.error(err);
    } finally {
        hideLoading();
    }
}

// ─── Send message ──────────────────────────────────────────────────────────────

async function sendMessage() {
    if (!sessionId) { showToast('Start a session first'); return; }
    if (isWaiting) return;

    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    // Clear input
    input.value = '';
    input.style.height = 'auto';

    // Append user message
    appendMessage('user', message);

    // Show typing indicator
    isWaiting = true;
    setSendLoading(true);
    showTyping(true);
    scrollToBottom();

    try {
        const res = await fetch(`${API_BASE}/chat/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, message }),
        });
        const data = await res.json();

        if (!data.success) throw new Error(data.message || 'Message failed');

        const resp = data.data;

        // Update progress
        updateProgress(resp.progress_pct, resp.required_remaining);

        // Render assistant reply
        const msgType = resp.status === 'analyzing' ? 'analysis' : 'assistant';
        appendMessage(msgType, resp.assistant_message);

        // Handle state transitions
        if (resp.ready || resp.status === 'analyzing') {
            handleAnalysisStarted();
        }

    } catch (err) {
        showToast(`Error: ${err.message}`);
        appendMessage('system', '⚠ Connection error. Please try again.');
        console.error(err);
    } finally {
        isWaiting = false;
        setSendLoading(false);
        showTyping(false);
        scrollToBottom();
    }
}

function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// ─── Analysis pipeline triggered ──────────────────────────────────────────────

function handleAnalysisStarted() {
    if (analysisStarted) return;
    analysisStarted = true;

    // Disable input while analysis runs
    document.getElementById('chat-input').disabled = true;
    document.getElementById('send-btn').disabled = true;
    document.getElementById('input-hint').textContent = 'Analysis running — please wait...';

    // Show status card
    document.getElementById('status-card').classList.remove('hidden');
    setStateLabel('RUNNING ANALYSIS');

    // Animate steps
    animateStatusSteps();

    // Poll for analysis completion then start roundtable
    pollAnalysisStatus();
}

function animateStatusSteps() {
    const steps = ['step-costs', 'step-financial', 'step-scenarios', 'step-behavioral'];
    let i = 0;

    // Mark first step active immediately
    document.getElementById(steps[0])?.classList.add('active');

    const interval = setInterval(() => {
        if (i > 0) {
            document.getElementById(steps[i - 1])?.classList.remove('active');
            document.getElementById(steps[i - 1])?.classList.add('done');
        }
        if (i < steps.length) {
            document.getElementById(steps[i])?.classList.add('active');
            i++;
        } else {
            clearInterval(interval);
        }
    }, 3000);
}

async function pollAnalysisStatus() {
    let attempts = 0;
    const maxAttempts = 60;   // 2 minutes max

    const poll = async () => {
        if (attempts++ > maxAttempts) {
            showToast('Analysis taking longer than expected. Connecting to roundtable...');
            connectRoundtable();
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/chat/status/${sessionId}`);
            const data = await res.json();
            const status = data.data?.status;

            if (status === 'roundtable' || status === 'analyzing') {
                // Mark behavioral done
                document.getElementById('step-behavioral')?.classList.remove('active');
                document.getElementById('step-behavioral')?.classList.add('done');
                document.getElementById('step-roundtable')?.classList.add('active');

                // Connect WebSocket for roundtable
                connectRoundtable();
                return;
            }

            if (status === 'error') {
                showToast(`Analysis error: ${data.data?.error || 'Unknown error'}`);
                return;
            }

            // Still collecting/analyzing — poll again
            setTimeout(poll, 2000);

        } catch (err) {
            setTimeout(poll, 3000);
        }
    };

    // Start polling after a short delay (let pipeline start)
    setTimeout(poll, 4000);
}

// ─── WebSocket Roundtable ──────────────────────────────────────────────────────

function connectRoundtable() {
    if (ws) return;   // already connected

    const wsUrl = `${WS_BASE}/chat/roundtable/${sessionId}`;
    ws = new WebSocket(wsUrl);

    // Show roundtable card
    document.getElementById('roundtable-card').classList.remove('hidden');
    document.getElementById('consensus-wrap').classList.remove('hidden');
    setStateLabel('AI ROUNDTABLE');

    ws.onopen = () => {
        document.getElementById('ws-dot').classList.add('connected');
        appendSystemMessage('Roundtable connected — AI experts are now debating your case');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleRoundtableEvent(msg);
        } catch (e) {
            console.warn('WS parse error:', e);
        }
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        showToast('Roundtable connection error');
    };

    ws.onclose = () => {
        document.getElementById('ws-dot').classList.remove('connected');
        console.log('WebSocket closed');
    };
}

function handleRoundtableEvent(msg) {
    switch (msg.type) {

        case 'roundtable_start':
            appendRTMessage(null, null,
                `Roundtable opened — ${msg.agents?.join(', ')} are reviewing your case`,
                'system'
            );
            break;

        case 'round_start':
            document.getElementById('round-indicator').classList.remove('hidden');
            document.getElementById('round-num').textContent = msg.round;
            appendSystemRTMessage(`— Round ${msg.round} of 4 —`);
            break;

        case 'agent_typing':
            showRTTyping(msg.agent);
            break;

        case 'agent_message':
            hideRTTyping();
            appendRTMessage(msg.agent, msg.message_type, msg.content);

            // Also surface key messages in main chat
            if (msg.message_type === 'conclusion') {
                appendMessage('assistant',
                    `**${msg.agent}:** ${msg.content}`
                );
            }
            break;

        case 'round_end':
            updateConsensus(msg.consensus_score || 0);
            break;

        case 'convergence':
            appendRTMessage(null, null, '✓ Experts reached consensus', 'system');
            document.getElementById('step-roundtable')?.classList.remove('active');
            document.getElementById('step-roundtable')?.classList.add('done');
            document.getElementById('step-report')?.classList.add('active');
            setStateLabel('GENERATING REPORT');
            break;

        case 'verdict_ready':
            handleVerdictReady(msg.data);
            break;

        case 'error':
            showToast(`Roundtable error: ${msg.message}`);
            appendSystemMessage(`⚠ ${msg.message}`);
            break;

        default:
            break;
    }
    scrollRTToBottom();
}

// ─── Verdict received ─────────────────────────────────────────────────────────

function handleVerdictReady(verdict) {
    if (!verdict) return;

    // Mark report step done
    document.getElementById('step-report')?.classList.remove('active');
    document.getElementById('step-report')?.classList.add('done');

    // Show report card
    document.getElementById('report-card').classList.remove('hidden');

    // Verdict badge
    const verdictStr = String(verdict.verdict || 'wait').toLowerCase().replace('_', ' ');
    const badge = document.getElementById('verdict-badge');
    badge.textContent = verdictStr.toUpperCase();
    badge.className = 'verdict-badge';
    if (verdictStr.includes('buy safe')) badge.classList.add('buy-safe');
    else if (verdictStr.includes('caution')) badge.classList.add('buy-caution');
    else if (verdictStr.includes('wait')) badge.classList.add('wait');
    else if (verdictStr.includes('risky')) badge.classList.add('too-risky');

    // Risk score
    const scoreEl = document.getElementById('risk-score-val');
    // Risk score lives on the presentation object — try to get it via status
    fetch(`${API_BASE}/chat/status/${sessionId}`)
        .then(r => r.json())
        .catch(() => null);

    // Summary message in chat
    const narrative = verdict.final_narrative || 'Analysis complete.';
    appendMessage('analysis',
        `✓ Analysis complete.\n\n${narrative}\n\n` +
        `Verdict: **${verdictStr.toUpperCase()}** · Confidence: ${verdict.confidence?.toFixed(0)}%`
    );

    // Re-enable input for follow-up questions
    document.getElementById('chat-input').disabled = false;
    document.getElementById('send-btn').disabled = false;
    document.getElementById('input-hint').textContent =
        'Ask follow-up questions or download your report →';
    document.getElementById('chat-input').placeholder =
        'Ask a follow-up question...';

    setStateLabel('COMPLETE — REPORT READY');
    scrollToBottom();
}

// ─── Report download ──────────────────────────────────────────────────────────

function downloadReport() {
    if (!sessionId) { showToast('No active session'); return; }
    const url = `${API_BASE}/report/${sessionId}`;
    window.open(url, '_blank');
    showToast('Downloading report...');
}

// ─── UI helpers ───────────────────────────────────────────────────────────────

function appendMessage(role, content) {
    const messages = document.getElementById('messages');
    const div = document.createElement('div');

    if (role === 'system') {
        div.className = 'msg-system';
        div.textContent = content;
        messages.appendChild(div);
        return;
    }

    div.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = role === 'user' ? 'U' : 'N';

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';

    // Simple markdown — bold and newlines
    bubble.innerHTML = content
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');

    const time = document.createElement('div');
    time.className = 'msg-time';
    time.textContent = formatTime();

    const inner = document.createElement('div');
    inner.appendChild(bubble);
    inner.appendChild(time);

    div.appendChild(avatar);
    div.appendChild(inner);
    messages.appendChild(div);
    scrollToBottom();
}

function appendSystemMessage(text) {
    appendMessage('system', text);
}

function showTyping(show) {
    document.getElementById('typing-indicator').classList.toggle('hidden', !show);
    if (show) scrollToBottom();
}

function setSendLoading(loading) {
    const btn = document.getElementById('send-btn');
    const icon = document.getElementById('send-icon');
    btn.classList.toggle('loading', loading);
    btn.disabled = loading;
    icon.textContent = loading ? '…' : '⟶';
}

function updateProgress(pct, remaining) {
    document.getElementById('progress-bar').style.width = `${pct}%`;
    document.getElementById('progress-pct').textContent = `${pct}%`;

    if (remaining > 0) {
        document.getElementById('progress-text').textContent =
            `${remaining} field${remaining > 1 ? 's' : ''} remaining`;
    } else {
        document.getElementById('progress-text').textContent = 'All data collected';
        document.getElementById('progress-bar').classList.remove('accent');
        document.getElementById('progress-bar').classList.add('green');
    }
}

// ── Roundtable UI ─────────────────────────────────────────────────────────────

let rtTypingEl = null;

function appendRTMessage(agent, type, content, variant = 'normal') {
    const container = document.getElementById('roundtable-messages');

    if (variant === 'system') {
        const div = document.createElement('div');
        div.className = 'msg-system';
        div.style.fontSize = '0.48rem';
        div.style.margin = '2px 0';
        div.textContent = content;
        container.appendChild(div);
        return;
    }

    const div = document.createElement('div');
    div.className = 'rt-message';

    const header = document.createElement('div');
    header.className = 'rt-agent-header';

    const nameEl = document.createElement('span');
    nameEl.className = `rt-agent-name ${(agent || '').toLowerCase()}`;
    nameEl.textContent = agent || '';

    const typeEl = document.createElement('span');
    typeEl.className = 'rt-msg-type';
    typeEl.textContent = type || '';

    header.appendChild(nameEl);
    if (type) header.appendChild(typeEl);

    const contentEl = document.createElement('div');
    contentEl.className = 'rt-content';
    contentEl.textContent = content;

    div.appendChild(header);
    div.appendChild(contentEl);
    container.appendChild(div);
    scrollRTToBottom();
}

function appendSystemRTMessage(text) {
    appendRTMessage(null, null, text, 'system');
}

function showRTTyping(agentName) {
    hideRTTyping();
    const container = document.getElementById('roundtable-messages');
    rtTypingEl = document.createElement('div');
    rtTypingEl.className = 'rt-typing';
    rtTypingEl.innerHTML = `
    <span class="rt-agent-name ${agentName.toLowerCase()}">${agentName}</span>
    <span class="rt-typing-dots"><span></span><span></span><span></span></span>
  `;
    container.appendChild(rtTypingEl);
    scrollRTToBottom();
}

function hideRTTyping() {
    if (rtTypingEl) {
        rtTypingEl.remove();
        rtTypingEl = null;
    }
}

function updateConsensus(score) {
    document.getElementById('consensus-bar').style.width = `${score}%`;
    document.getElementById('consensus-pct').textContent = `${score}%`;
}

function scrollRTToBottom() {
    const el = document.getElementById('roundtable-messages');
    if (el) el.scrollTop = el.scrollHeight;
}

// ─── Reset ────────────────────────────────────────────────────────────────────

function resetChat() {
    if (ws) { ws.close(); ws = null; }

    sessionId = null;
    isWaiting = false;
    analysisStarted = false;

    // Clear messages
    document.getElementById('messages').innerHTML = '';
    document.getElementById('roundtable-messages').innerHTML = '';

    // Hide all panels
    document.getElementById('messages').classList.add('hidden');
    document.getElementById('input-row').classList.add('hidden');
    document.getElementById('input-hint').classList.add('hidden');
    document.getElementById('progress-wrap').classList.add('hidden');
    document.getElementById('status-card').classList.add('hidden');
    document.getElementById('roundtable-card').classList.add('hidden');
    document.getElementById('report-card').classList.add('hidden');
    document.getElementById('session-badge').classList.add('hidden');

    // Reset progress
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-pct').textContent = '0%';
    document.getElementById('consensus-bar').style.width = '0%';

    // Reset status steps
    document.querySelectorAll('.status-step').forEach(el => {
        el.classList.remove('active', 'done');
    });

    // Show splash
    document.getElementById('welcome-splash').style.display = '';

    // Re-enable input
    const input = document.getElementById('chat-input');
    input.disabled = false;
    input.value = '';
    input.style.height = 'auto';
    input.placeholder = 'Tell me about the property you\'re considering...';

    document.getElementById('send-btn').disabled = false;
    document.getElementById('send-icon').textContent = '⟶';
    document.getElementById('input-hint').textContent =
        'Press Enter to send · Shift+Enter for new line';

    setStateLabel('READY');
}

// ─── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Verify backend is reachable
    fetch(`${API_BASE}/health`)
        .then(r => r.json())
        .then(d => {
            if (d.status === 'healthy') {
                console.log('[NIV AI] Backend healthy — Groq:', d.groq);
            }
        })
        .catch(() => {
            showToast('Backend offline — check server is running on port 8000');
        });
});