const API = ''; // Update if backend is hosted elsewhere

// --- STATE VARIABLES ---
let currentStep = 1;
let selectedLanguage = 'english';
let frictionGateAnswers = {};
let lastInput = null;
let lastReport = null;
let whatIfOriginal = null;
let whatIfDebounceTimer = null;
let lastInput_cached = null;
let comparisonReport = null;
let currentShareUrl = '';

// --- HELPERS ---
function esc(s) { const d = document.createElement('div'); d.textContent = String(s || ''); return d.innerHTML; }
function inr(n) { if (n == null) return '—'; return '₹' + Math.round(n).toLocaleString('en-IN'); }
function pct(n) { return (n * 100).toFixed(1) + '%'; }
function getNum(id) { return +document.getElementById(id)?.value || 0; }
function getVal(id) { return document.getElementById(id)?.value || ''; }
function preview(el, previewId) {
    const v = +el.value; const p = document.getElementById(previewId);
    if (!p) return; p.textContent = v > 0 ? '= ' + inr(v) : '';
}

// --- WIZARD & LANGUAGE TOGGLE ---
function setLang(lang, btn) {
    selectedLanguage = lang;
    document.querySelectorAll('.lang-opt').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function goStep(n) {
    // Validation
    if (n === 2 && currentStep === 1) {
        const inc = getNum('monthly_income');
        if (inc <= 0) {
            document.getElementById('monthly_income').setAttribute('aria-invalid', 'true');
            document.getElementById('monthly_income').focus();
            showErr('Monthly income is required to proceed.');
            return;
        }
        document.getElementById('monthly_income').removeAttribute('aria-invalid');
        document.getElementById('err').style.display = 'none';
    }
    if (n === 3 && currentStep === 2) {
        const price = getNum('property_price');
        const loc = getVal('location_area');
        const dp = getNum('down_payment_available');
        if (price <= 100000) { showErr('Property price must be > ₹1,00,000'); return; }
        if (!loc) { showErr('Location is required'); return; }
        if (dp >= price) { showErr('Down payment must be less than property price'); return; }
        document.getElementById('err').style.display = 'none';
    }

    document.querySelectorAll('[data-step]').forEach(el => el.classList.remove('active'));
    document.querySelector(`[data-step="${n}"]`).classList.add('active');

    document.querySelectorAll('.w-step').forEach((el, idx) => {
        el.classList.remove('active', 'completed');
        if (idx + 1 < n) el.classList.add('completed');
        if (idx + 1 === n) el.classList.add('active');
    });
    
    // Fill the connector lines
    const fill1 = document.getElementById('w-fill-1');
    const fill2 = document.getElementById('w-fill-2');
    if (fill1 && fill2) {
        if (n === 1) { fill1.style.width = '0%'; fill2.style.width = '0%'; }
        else if (n === 2) { fill1.style.width = '100%'; fill2.style.width = '0%'; }
        else if (n === 3) { fill1.style.width = '100%'; fill2.style.width = '100%'; }
    }

    currentStep = n;
    window.scrollTo(0, 0);
    if (n === 2) { updateEMIPreview(); loadMarketRates(); }
}

function showAllSteps(e) {
    e.preventDefault();
    document.querySelector('.wizard-bar').style.display = 'none';
    document.querySelectorAll('[data-step]').forEach(el => el.classList.add('active'));
    e.target.style.display = 'none';
    const btn = document.createElement('button');
    btn.className = 'btn-primary';
    btn.textContent = 'Run Full AI Analysis — 6 Agents';
    btn.onclick = onSubmitClick;
    document.querySelector('[data-step="3"]').appendChild(btn);
}

// --- NEW FIELD HANDLERS ---
async function verifyGST() {
    const gstin = getVal('builder_gstin');
    const resDiv = document.getElementById('gst-result');
    if(!gstin) return;
    
    resDiv.textContent = "Verifying...";
    resDiv.style.color = "var(--text-dim)";
    
    try {
        const res = await fetch(`${API}/api/v1/tools/gst-check?gstin=${encodeURIComponent(gstin)}`);
        const data = await res.json();
        
        if (res.ok && data.legal_name) {
            resDiv.innerHTML = `<span style="color:var(--green)">✓ Valid: ${esc(data.legal_name)}</span>`;
            document.getElementById('builder_name').value = data.legal_name; // Sync across fields
        } else {
            resDiv.textContent = "⚠️ Could not resolve GSTIN";
            resDiv.style.color = "var(--yellow)";
        }
    } catch(e) {
        resDiv.textContent = "Error verifying GST";
    }
}

// --- LIVE METRICS (STEP 1 & 2) ---
function updateFinancialHealth() {
    const inc = getNum('monthly_income'); const sp = getNum('spouse_income');
    const emis = getNum('existing_emis'); const exp = getNum('monthly_expenses');
    const capacity = inc + sp - emis - exp;
    const el = document.getElementById('financial-health');
    if(el) {
        el.textContent = inr(capacity);
        el.style.color = capacity > 20000 ? 'var(--green)' : capacity >= 5000 ? 'var(--yellow)' : 'var(--red)';
    }
    const fill = document.getElementById('health-fill-bar');
    if(fill) {
        const pct = Math.min(Math.max((capacity / (inc + sp > 0 ? inc + sp : 1)) * 100, 0), 100);
        fill.style.width = pct + '%';
        fill.style.background = capacity > 20000 ? 'var(--green)' : capacity >= 5000 ? 'var(--yellow)' : 'var(--red)';
    }
}

function calculateClientEMI(principal, annualRatePct, tenureYears) {
    if (principal <= 0 || annualRatePct <= 0 || tenureYears <= 0) return 0;
    const r = annualRatePct / 12 / 100;
    const n = tenureYears * 12;
    return principal * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1);
}

let marketRatesData = null;

let emiDebounce;
function updateEMIPreview() {
    clearTimeout(emiDebounce);
    emiDebounce = setTimeout(() => {
        const price = getNum('property_price'); const dp = getNum('down_payment_available');
        const tenure = getNum('loan_tenure_years') || 20; const rate = getNum('expected_interest_rate') || 8.5;
        const inc = getNum('monthly_income'); const sp = getNum('spouse_income');
        const emis = getNum('existing_emis'); const exp = getNum('monthly_expenses');

        const principal = Math.max(price - dp, 0);
        const emi = Math.round(calculateClientEMI(principal, rate, tenure));
        const household = inc + sp;
        const surplus = household - emi - emis - exp;
        const ratio = household > 0 ? emi / household : 0;

        document.getElementById('ep-loan').textContent = principal > 0 ? inr(principal) : '—';
        document.getElementById('ep-emi').textContent = emi > 0 ? inr(emi) : '—';

        const surpEl = document.getElementById('ep-surplus');
        surpEl.textContent = surplus !== 0 ? (surplus >= 0 ? inr(surplus) : '−' + inr(Math.abs(surplus))) : '—';
        surpEl.style.color = surplus > 20000 ? 'var(--green)' : surplus > 5000 ? 'var(--yellow)' : 'var(--red)';

        const ratioEl = document.getElementById('ep-ratio');
        ratioEl.textContent = ratio > 0 ? (ratio * 100).toFixed(1) + '%' : '—';
        ratioEl.style.color = ratio < 0.30 ? 'var(--green)' : ratio < 0.45 ? 'var(--yellow)' : 'var(--red)';

        const zoneEl = document.getElementById('ep-zone');
        if (ratio < 0.30) {
            zoneEl.style.color = 'var(--green-light)';
            zoneEl.textContent = 'COMFORTABLE — EMI is safely within limits';
        } else if (ratio < 0.45) {
            zoneEl.style.color = 'var(--yellow-light)';
            zoneEl.textContent = 'STRETCHED — manageable but thin margin';
        } else if (ratio > 0) {
            zoneEl.style.color = 'var(--red-light)';
            zoneEl.textContent = 'DANGER — this EMI is dangerously high';
        } else {
            zoneEl.textContent = '';
        }
        // Show rate warning if market data is loaded
        if (marketRatesData && rate > 0) updateRateWarning(rate, marketRatesData);
    }, 300);
}

// --- FRICTION GATE ---
function shouldShowFrictionGate() {
    const isUC = getVal('is_ready_to_move') === 'false';
    const dp = getNum('down_payment_available'); const sav = getNum('liquid_savings');
    const dpRatio = sav > 0 ? dp / sav : 0;
    const hh = getNum('monthly_income') + getNum('spouse_income');
    const emi = calculateClientEMI(Math.max(getNum('property_price') - dp, 0), getNum('expected_interest_rate') || 8.5, getNum('loan_tenure_years') || 20);
    const emiRatio = hh > 0 ? emi / hh : 0;
    return isUC || dpRatio > 0.60 || emiRatio > 0.40;
}

function onSubmitClick() {
    if (shouldShowFrictionGate()) {
        document.getElementById('friction-gate').style.display = 'flex';
        document.getElementById('fq3').style.display = getVal('is_ready_to_move') === 'false' ? 'block' : 'none';
        document.getElementById('fq5').style.display = getVal('builder_name') ? 'block' : 'none';
        checkFrictionComplete();
    } else {
        submitAnalysis();
    }
}

function selectFriction(qId, val) {
    frictionGateAnswers[qId] = val;
    const qDiv = document.getElementById(qId);
    qDiv.querySelectorAll('.friction-option').forEach(el => el.classList.remove('selected'));
    event.target.classList.add('selected');

    const warn = qDiv.querySelector('.friction-warning');
    if (val === 'C' || (val === 'B' && qId !== 'fq3')) {
        warn.style.display = 'block';
    } else {
        warn.style.display = 'none';
    }
    checkFrictionComplete();
}

function checkFrictionComplete() {
    // Use computed style so fq3/fq5 (shown via inline style, no .active class) are correctly counted
    const visibleQs = Array.from(document.querySelectorAll('.friction-question')).filter(
        el => window.getComputedStyle(el).display !== 'none'
    );
    const answeredCount = visibleQs.filter(el => frictionGateAnswers[el.id]).length;
    const btn = document.getElementById('friction-proceed');

    if (answeredCount === visibleQs.length && visibleQs.length > 0) {
        btn.disabled = false;
        const concerns = Object.entries(frictionGateAnswers).filter(([k, v]) => v === 'C' || (v === 'B' && k !== 'fq3')).length;
        const sumEl = document.getElementById('friction-summary');
        sumEl.style.display = 'block';
        if (concerns === 0) {
            sumEl.style.background = 'var(--green-bg)'; sumEl.style.color = 'var(--green)';
            sumEl.textContent = '✓ You\'ve done your homework — proceeding to analysis.';
        } else if (concerns <= 2) {
            sumEl.style.background = 'var(--yellow-bg)'; sumEl.style.color = 'var(--yellow)';
            sumEl.textContent = '⚠ A few things to keep in mind during the analysis.';
        } else {
            sumEl.style.background = 'var(--red-bg)'; sumEl.style.color = 'var(--red)';
            sumEl.textContent = '✗ The analysis will surface these risks — read it carefully.';
        }
    } else {
        btn.disabled = true;
    }
}

function closeFrictionGate() { document.getElementById('friction-gate').style.display = 'none'; }
function proceedFromFriction() { closeFrictionGate(); submitAnalysis(); }

// --- SUBMISSION & API ---
function collectFormData() {
    const r = getVal('is_rera_registered');
    
    let combinedNotes = getVal('property_notes') || '';
    const gstin = getVal('builder_gstin');
    const rera = getVal('rera_number');
    if (gstin) combinedNotes += (combinedNotes ? ' | ' : '') + 'Builder GSTIN: ' + gstin;
    if (rera) combinedNotes += (combinedNotes ? ' | ' : '') + 'RERA Number: ' + rera;

    return {
        financial: {
            monthly_income: getNum('monthly_income'), spouse_income: getNum('spouse_income'),
            employment_type: getVal('employment_type'), years_in_current_job: getNum('years_in_current_job') || 2,
            expected_annual_growth_pct: getNum('expected_annual_growth_pct') || 8,
            existing_emis: getNum('existing_emis'), monthly_expenses: getNum('monthly_expenses'),
            current_rent: getNum('current_rent'), liquid_savings: getNum('liquid_savings'),
            dependents: getNum('dependents'), financial_notes: getVal('financial_notes')
        },
        property: {
            property_price: getNum('property_price'), location_area: getVal('location_area') || 'Mumbai',
            location_city: 'Mumbai', configuration: getVal('configuration'),
            carpet_area_sqft: getNum('carpet_area_sqft') || 650,
            is_ready_to_move: getVal('is_ready_to_move') === 'true',
            is_rera_registered: r === 'null' ? null : r === 'true',
            builder_name: getVal('builder_name'), possession_date: getVal('possession_date'),
            down_payment_available: getNum('down_payment_available'),
            loan_tenure_years: getNum('loan_tenure_years') || 20,
            expected_interest_rate: getNum('expected_interest_rate') || 8.5,
            buyer_gender: getVal('buyer_gender'), commute_distance_km: getNum('commute_distance_km') || 0,
            is_first_property: getVal('is_first_property') === 'true', property_notes: combinedNotes
        },
        output_language: selectedLanguage,
        behavioral_checklist_responses: Object.keys(frictionGateAnswers).length ? frictionGateAnswers : null
    };
}

let _t = null;
function setA(id, st) {
    const el = document.getElementById(id); el.className = 'arow ' + st;
    el.querySelector('.astatus').textContent = st === 'running' ? 'running…' : st === 'done' ? '✓ done' : 'waiting';
}
function startA() {
    const ids = ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']; let i = 0;
    function t() { if (i > 0) setA(ids[i - 1], 'done'); if (i < ids.length) { setA(ids[i], 'running'); i++; _t = setTimeout(t, 4000); } }
    t();
}
function stopA() { clearTimeout(_t);['a1', 'a2', 'a3', 'a4', 'a5', 'a6'].forEach(id => setA(id, 'done')); }

function showErr(m) { const el = document.getElementById('err'); el.style.display = 'block'; el.textContent = '⚠ ' + m; window.scrollTo(0, 0); }

async function submitAnalysis() {
    document.getElementById('err').style.display = 'none';
    const body = collectFormData();
    lastInput = body;

    document.getElementById('form-section').style.display = 'none';
    document.getElementById('loading').style.display = 'block';
    document.getElementById('report').style.display = 'none';
    startA();

    try {
        const res = await fetch(`${API}/api/v1/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!res.ok) { const e = await res.json().catch(() => { }); throw new Error(e?.detail || `HTTP ${res.status}`); }
        const data = await res.json();
        lastReport = data;
        stopA();
        document.getElementById('loading').style.display = 'none';
        renderReport(data);
        document.getElementById('report').style.display = 'block';
        window.scrollTo(0, 0);
        autoSaveReport(data);
    } catch (e) {
        stopA();
        document.getElementById('loading').style.display = 'none';
        document.getElementById('form-section').style.display = 'block';
        showErr('Analysis failed: ' + e.message);
    }
}

// --- RENDERING ---
function renderReport(r) {
    const c = r.computed_numbers || {};
    const v = (r.verdict || 'risky').toLowerCase();
    document.getElementById('compare-bar').style.display = 'block';

    // Verdict
    document.getElementById('r-verdict').innerHTML = `
                <div class="verdict-display" aria-label="Analysis verdict: ${v}">
                    <div class="verdict-word ${v.toUpperCase()}">${esc(v).toUpperCase()}</div>
                    <div style="font-family:var(--font-mono); font-size:14px; margin-bottom:24px;">${esc(r.verdict_reason || '')}</div>
                    <div class="verdict-meta">
                        <span class="badge ${v === 'safe' ? 'low' : v === 'reconsider' ? 'critical' : 'high'}">CONFIDENCE: ${r.confidence_score || '?'}/10</span>
                    </div>
                </div>`;

    // Research Warnings
    const rw = r.research_warnings || [];
    const rwDiv = document.getElementById('r-research-warnings');
    if (rw.length > 0) {
        rwDiv.style.display = 'block';
        rwDiv.innerHTML = `<div class="section-label" style="display:none;"><span>02 ·</span> RESEARCH WARNINGS</div>` +
            rw.map(w => `<div class="research-warning ${w.severity}"><div style="font-family:var(--font-mono); font-size:10px; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">${w.severity} SEVERITY</div><div style="font-size:14px; color:var(--text); margin-bottom:8px;">${esc(w.stat)}</div><div style="font-family:var(--font-mono); font-size:10px; color:var(--text-muted)">Source: ${esc(w.source)}</div></div>`).join('');
    } else { rwDiv.style.display = 'none'; }

    // Cashflow
    const household = (lastInput?.financial?.monthly_income || 0) + (lastInput?.financial?.spouse_income || 0);
    const existEMIs = lastInput?.financial?.existing_emis || 0;
    const expenses = lastInput?.financial?.monthly_expenses || 0;
    const emi = c.monthly_emi || 0;
    const ownership = c.monthly_ownership_cost || 0;
    const surplus = household - ownership - existEMIs - expenses;
    const surplusCls = surplus > 20000 ? 'good' : surplus > 5000 ? 'warn' : 'crit';
    const barPct = (n) => Math.min(Math.max((n / household) * 100, 2), 100).toFixed(1);

    document.getElementById('r-cashflow').innerHTML = `
                <div class="cf-title">💸 Your Monthly Cash Flow After Purchase</div>
                <div class="cf-main">
                    <div class="cf-surplus-box">
                        <div class="cf-surplus-label">Monthly Surplus</div>
                        <div class="cf-surplus-value ${surplusCls}">${surplus >= 0 ? inr(surplus) : '−' + inr(Math.abs(surplus))}</div>
                        <div class="cf-surplus-sub ${surplusCls}">${surplus > 20000 ? '✓ Healthy buffer' : surplus > 5000 ? '⚠ Thin margin' : '✗ Critical deficit'}</div>
                    </div>
                    <div class="cf-waterfall">
                        <div class="cf-row"><span class="cf-row-label">Total Income</span><span class="cf-row-amount income">+${inr(household)}</span><div class="cf-bar-wrap"><div class="cf-bar income" style="width:100%"></div></div></div>
                        <div class="cf-row"><span class="cf-row-label">New Home EMI</span><span class="cf-row-amount out">−${inr(emi)}</span><div class="cf-bar-wrap"><div class="cf-bar out" style="width:${barPct(emi)}%"></div></div></div>
                        <div class="cf-row"><span class="cf-row-label">Maint + Insur</span><span class="cf-row-amount out">−${inr(ownership - emi)}</span><div class="cf-bar-wrap"><div class="cf-bar out" style="width:${barPct(ownership - emi)}%"></div></div></div>
                        ${existEMIs > 0 ? `<div class="cf-row"><span class="cf-row-label">Existing EMIs</span><span class="cf-row-amount out">−${inr(existEMIs)}</span><div class="cf-bar-wrap"><div class="cf-bar out" style="width:${barPct(existEMIs)}%"></div></div></div>` : ''}
                        <div class="cf-row"><span class="cf-row-label">Living Expenses</span><span class="cf-row-amount out">−${inr(expenses)}</span><div class="cf-bar-wrap"><div class="cf-bar out" style="width:${barPct(expenses)}%"></div></div></div>
                    </div>
                </div>`;

    // Scorecard
    const sc = (state, label, val, verdict, ctx) => {
        let stColor = state === 'pass' ? 'var(--green)' : state === 'warn' ? 'var(--yellow)' : state === 'neutral' ? 'var(--text-faint)' : 'var(--red)';
        return `<div class="metric-cell" aria-label="${label}: ${val}, status ${state}">
                    <div class="metric-label">${label}</div>
                    <div class="metric-number">${val}</div>
                    <div class="metric-status" style="color:${stColor}">${state === 'pass' ? 'PASS' : state === 'warn' ? 'CAUTION' : state === 'neutral' ? 'INFO' : 'FAIL'} · ${verdict}</div>
                </div>`;
    };

    const emiR = c.emi_to_income_ratio || 0; const runway = c.emergency_runway_months || 0;
    const dpR = c.down_payment_to_savings_ratio || 0; const spass = (r.stress_scenarios || []).filter(s => s.can_survive).length;
    const crits = (r.assumptions_challenged || []).filter(a => ['critical', 'high'].includes(a.severity)).length;
    const pv = r.property_assessment?.price_assessment?.verdict || '';

    document.getElementById('r-scorecard').innerHTML = `<div class="metric-grid">` +
        sc(emiR < .30 ? 'pass' : emiR < .45 ? 'warn' : 'fail', 'EMI/Income', pct(emiR), emiR < .30 ? '✓ Healthy' : emiR < .45 ? '⚠ Stretched' : '✗ Too High', `EMI ${inr(emi)}`) +
        sc(runway >= 6 ? 'pass' : runway >= 3 ? 'warn' : 'fail', 'Runway', runway.toFixed(1) + 'mo', runway >= 6 ? '✓ Safe' : runway >= 3 ? '⚠ Low' : '✗ Critical', `Savings ${inr(c.post_purchase_savings)}`) +
        sc(dpR < .60 ? 'pass' : dpR < .80 ? 'warn' : 'fail', 'Savings Used', pct(dpR), dpR < .60 ? '✓ Safe' : '⚠ High', `${inr(lastInput?.property?.down_payment_available)} down`) +
        sc(spass >= 3 ? 'pass' : spass >= 2 ? 'warn' : 'fail', 'Stress Tests', `${spass}/4`, spass >= 3 ? '✓ Resilient' : '✗ Vulnerable', 'Scenarios passed') +
        sc(v === 'safe' ? (crits === 0 ? 'pass' : 'neutral') : (crits === 0 ? 'pass' : 'fail'), 'Risk Flags', crits.toString(), crits === 0 ? '✓ Clear' : `⚠ ${crits} risks`, 'High severity flags') +
        sc({ good_value: 'pass', fair: 'pass', overpriced: 'fail' }[pv] || 'neutral', 'Price', inr(r.property_assessment?.price_assessment?.price_per_sqft) + '/sqf', pv.replace('_', ' ').toUpperCase(), 'vs Area Median')
        + `</div>`;

    // True Cost
    if (c.true_total_acquisition_cost) {
        document.getElementById('r-tco').innerHTML = `
                <table class="dtable">
                    <tr><td>Base Property Price</td><td>${inr(lastInput?.property?.property_price)}</td></tr>
                    <tr><td>Taxes & Registration</td><td>${inr((c.total_acquisition_cost || 0) - (lastInput?.property?.property_price || 0))}</td></tr>
                    <tr><td>Estimated Interiors (12%)</td><td>${inr(c.interiors_estimated_cost)}</td></tr>
                    <tr style="border-top:2px solid var(--border);font-weight:700"><td style="color:var(--text)">True Upfront Cost</td><td>${inr(c.true_total_acquisition_cost)}</td></tr>
                    <tr><td>10-Yr Opp. Cost (if invested at 12%)</td><td style="color:var(--yellow)">${inr(c.down_payment_opportunity_cost_10yr)}</td></tr>
                </table>`;
    } else { document.getElementById('r-tco').parentElement.style.display = 'none'; }

    // Simple sections mapping
    document.getElementById('r-stress').innerHTML = (r.stress_scenarios || []).map(s => `
        <div class="stress-row">
            <div class="stress-indicator ${s.can_survive ? 'pass' : 'fail'}"></div>
            <div class="stress-name">${esc(s.name.replace(/_/g, ' ').toUpperCase())}</div>
            <div class="stress-key-number">${esc(s.key_number)}</div>
            <div class="stress-badge" style="color:${s.can_survive ? 'var(--green)' : 'var(--red)'}">${s.can_survive ? 'SURVIVES' : 'AT RISK'}</div>
        </div>`).join('');

    // Path to Safe
    if (r.path_to_safe) {
        const ps = document.getElementById('r-path-to-safe');
        ps.style.display = 'block';
        ps.innerHTML = `<div class="rcard" style="border-color:var(--green);"><div style="font-family:var(--font-mono); font-size:12px; color:var(--green); letter-spacing:1px; margin-bottom:16px;">💡 PATH TO SAFE</div><div style="font-size:14px;color:var(--text); line-height:1.7;">To achieve a SAFE verdict, you must either increase your down payment by <strong style="color:var(--green)">${inr(r.path_to_safe.min_additional_down_payment)}</strong> OR reduce the property price to <strong style="color:var(--green)">${inr(r.path_to_safe.max_viable_property_price)}</strong>. At your current savings rate, gathering this extra down payment will take approx <strong style="color:var(--text)">${r.path_to_safe.months_to_save_at_current_rate.toFixed(1)} months</strong>.</div></div>`;
    } else { document.getElementById('r-path-to-safe').style.display = 'none'; }

    const pa = r.property_assessment || {};
    document.getElementById('r-property').innerHTML =
        `<table class="dtable"><tr><td>Your price/sqft</td><td>${inr(pa.price_assessment?.price_per_sqft)}</td></tr><tr><td>Area median</td><td>${inr(pa.price_assessment?.area_median_per_sqft)}</td></tr></table>` +
        (pa.property_flags || []).map(f => `<div class="flag ${f.severity}"><span class="flag-sev-text">${f.severity.toUpperCase()}</span><span class="flag-name">${esc(f.flag)}</span> — ${esc(f.detail)}</div>`).join('') +
        renderOcCcStatus(pa.oc_cc_status);

    const rvb = r.rent_vs_buy || {};
    document.getElementById('r-rvb').innerHTML = `<div class="rvb-compare"><div class="rvb-box rent"><div class="rvb-box-label">If You Rent</div><div class="rvb-box-val">${inr(rvb.equivalent_monthly_rent)}</div></div><div class="rvb-box buy"><div class="rvb-box-label">If You Buy</div><div class="rvb-box-val">${inr(rvb.buying_monthly_cost)}</div></div></div><div class="rvb-diff">Break-even is <strong>${(c.rent_vs_buy_break_even_years || 0).toFixed(1)} years</strong>.</div>`;

    document.getElementById('r-challenges').innerHTML = (r.assumptions_challenged || []).map(ch => `<div class="challenge ${ch.severity}"><div class="ch-top"><span class="sev ${ch.severity}">${ch.severity}</span><span class="ch-assume">${esc(ch.assumption)}</span></div><div class="ch-body">${esc(ch.challenge)}</div></div>`).join('');
    document.getElementById('r-reasons').innerHTML = (r.top_reasons || []).map(t => `<li>${esc(t)}</li>`).join('');
    document.getElementById('r-actions').innerHTML = (r.recommended_actions || []).map(a => `<li>${esc(a)}</li>`).join('');
    document.getElementById('r-reasoning').textContent = r.full_reasoning || '';
    document.getElementById('r-blind').innerHTML = (r.blind_spots || []).map(b => `<div class="pill">${esc(b)}</div>`).join('');
    document.getElementById('r-emo').innerHTML = (r.emotional_flags || []).map(f => `<div class="pill" style="border-color:var(--accent-dim);color:#a89cf7">${esc(f)}</div>`).join('');

    let covMsg = "";
    if (r.benchmark_coverage?.coverage_level === "default") {
        covMsg = `<span style="color:var(--red)">⚠ ${esc(r.benchmark_coverage.warning)}</span> · `;
    } else if (r.benchmark_coverage?.coverage_level === "partial") {
        covMsg = `<span style="color:var(--yellow)">⚠ Partial benchmark data</span> · `;
    }

    document.getElementById('r-meta').innerHTML = `${covMsg}Analysis in ${r._meta?.pipeline_time_seconds || '?'}s · ${(r.data_sources || []).join(' · ')}`;

    initWhatIf(r);
}

// --- WHAT-IF SLIDERS ---
function initWhatIf(report) {
    const c = report.computed_numbers || {};
    whatIfOriginal = { ...c }; lastInput_cached = { ...lastInput };
    const p = lastInput.property;

    const dp = document.getElementById('wi-dp');
    dp.min = Math.max(0, p.down_payment_available - 1000000); dp.max = p.property_price * 0.9; dp.value = p.down_payment_available;

    const pr = document.getElementById('wi-price');
    pr.min = Math.round(p.property_price * 0.8 / 50000) * 50000; pr.max = Math.round(p.property_price * 1.1 / 50000) * 50000; pr.value = p.property_price;

    const tn = document.getElementById('wi-tenure');
    tn.value = p.loan_tenure_years || 20;

    document.getElementById('r-whatif').style.display = 'block';
    ['wi-dp', 'wi-price', 'wi-tenure'].forEach(id => {
        document.getElementById(id).addEventListener('input', onWhatIfSlide);
        document.getElementById(id + '-val').textContent = id === 'wi-tenure' ? document.getElementById(id).value + ' yrs' : inr(+document.getElementById(id).value);
    });
    updateWhatIfDisplay(c, c);
}

function onWhatIfSlide() {
    document.getElementById('wi-dp-val').textContent = inr(+document.getElementById('wi-dp').value);
    document.getElementById('wi-price-val').textContent = inr(+document.getElementById('wi-price').value);
    document.getElementById('wi-tenure-val').textContent = document.getElementById('wi-tenure').value + ' yrs';
    clearTimeout(whatIfDebounceTimer);
    whatIfDebounceTimer = setTimeout(fetchWhatIf, 400);
}

async function fetchWhatIf() {
    if (!lastInput_cached) return;
    const fin = lastInput_cached.financial; const prop = lastInput_cached.property;
    const params = new URLSearchParams({
        monthly_income: fin.monthly_income, spouse_income: fin.spouse_income || 0,
        existing_emis: fin.existing_emis || 0, monthly_expenses: fin.monthly_expenses || 0,
        liquid_savings: fin.liquid_savings || 0, property_price: +document.getElementById('wi-price').value,
        down_payment: +document.getElementById('wi-dp').value, loan_tenure_years: +document.getElementById('wi-tenure').value,
        interest_rate: prop.expected_interest_rate || 8.5, carpet_area_sqft: prop.carpet_area_sqft || 650,
        is_ready_to_move: prop.is_ready_to_move !== false, location_area: prop.location_area || ''
    });
    try {
        const res = await fetch(`${API}/api/v1/calculate?${params}`);
        if (res.ok) updateWhatIfDisplay(await res.json(), whatIfOriginal);
    } catch (e) { }
}

function updateWhatIfDisplay(curr, orig) {
    const hh = (lastInput_cached?.financial?.monthly_income || 0) + (lastInput_cached?.financial?.spouse_income || 0);
    const fixed = (lastInput_cached?.financial?.existing_emis || 0) + (lastInput_cached?.financial?.monthly_expenses || 0);

    const setM = (id, cur, ori, fmt, hBetter) => {
        document.getElementById(id).textContent = fmt(cur);
        const dEl = document.getElementById(id + '-d');
        const diff = cur - ori;
        if (Math.abs(diff) < 0.01) { dEl.textContent = ''; return; }
        const sign = diff > 0 ? '+' : '';
        dEl.textContent = `${sign}${fmt(diff)} vs orig`;
        dEl.className = 'wm-delta ' + ((hBetter ? diff > 0 : diff < 0) ? 'better' : 'worse');
    };

    setM('wm-emi', curr.monthly_emi, orig.monthly_emi, inr, false);
    setM('wm-surplus', hh - curr.monthly_emi - fixed, hh - orig.monthly_emi - fixed, inr, true);
    setM('wm-runway', curr.emergency_runway_months, orig.emergency_runway_months, v => v.toFixed(1) + 'mo', true);

    const ratioEl = document.getElementById('wm-ratio');
    ratioEl.textContent = (curr.emi_to_income_ratio * 100).toFixed(1) + '%';
    ratioEl.style.color = curr.emi_to_income_ratio < 0.3 ? 'var(--green)' : curr.emi_to_income_ratio < 0.45 ? 'var(--yellow)' : 'var(--red)';
    const rDiff = curr.emi_to_income_ratio - orig.emi_to_income_ratio;
    const rDel = document.getElementById('wm-ratio-d');
    if (Math.abs(rDiff) > 0.001) {
        rDel.textContent = `${rDiff > 0 ? '+' : ''}${(rDiff * 100).toFixed(1)}% vs orig`;
        rDel.className = 'wm-delta ' + (rDiff < 0 ? 'better' : 'worse');
    } else { rDel.textContent = ''; }
}

function resetWhatIf() { if (whatIfOriginal) initWhatIf({ computed_numbers: whatIfOriginal }); }

// --- COMPARISON ---
function startComparison() { document.getElementById('compare-form').style.display = 'block'; document.getElementById('compare-bar').style.display = 'none'; }
function cancelComparison() { document.getElementById('compare-form').style.display = 'none'; document.getElementById('compare-bar').style.display = 'block'; }
function clearComparison() { document.getElementById('compare-results').style.display = 'none'; document.getElementById('compare-bar').style.display = 'block'; }

async function runComparison() {
    const p2 = +document.getElementById('c_price').value; const l2 = getVal('c_loc');
    if (!p2 || !l2) return alert('Price and Location required');
    const body = { financial: { ...lastInput.financial }, property: { ...lastInput.property, property_price: p2, location_area: l2, down_payment_available: getNum('c_dp') || Math.round(p2 * .2), carpet_area_sqft: getNum('c_sqft') || 650, is_ready_to_move: getVal('c_rdy') === 'true', builder_name: getVal('c_bld') } };
    const btn = document.querySelector('#compare-form .btn-primary'); btn.disabled = true; btn.textContent = 'Analyzing...';
    try {
        const res = await fetch(`${API}/api/v1/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (res.ok) renderComparisonTable(lastReport, await res.json());
    } finally { btn.disabled = false; btn.textContent = 'Analyze Property 2'; }
}

function renderComparisonTable(r1, r2) {
    comparisonReport = r2;
    const c1 = r1.computed_numbers || {};
    const c2 = r2.computed_numbers || {};
    const loc1 = lastInput?.property?.location_area || 'Property 1';
    const loc2 = document.getElementById('c_loc').value || 'Property 2';

    const better = (v1, v2, higherIsBetter) => {
        if (v1 == null || v2 == null) return 'tie';
        return higherIsBetter ? (v1 > v2 ? '1' : v1 < v2 ? '2' : 'tie')
            : (v1 < v2 ? '1' : v1 > v2 ? '2' : 'tie');
    };

    const verdictOrder = { safe: 0, risky: 1, reconsider: 2 };
    const v1 = r1.verdict || 'risky';
    const v2 = r2.verdict || 'risky';
    const verdictBetter = verdictOrder[v1] <= verdictOrder[v2] ? '1' : '2';
    const ss1 = (r1.stress_scenarios || []).filter(s => s.can_survive).length;
    const ss2 = (r2.stress_scenarios || []).filter(s => s.can_survive).length;
    const pv1 = r1.property_assessment?.price_assessment?.premium_over_market_pct || 0;
    const pv2 = r2.property_assessment?.price_assessment?.premium_over_market_pct || 0;

    const rows = [
        { metric: 'Overall Verdict', v1: v1.toUpperCase(), v2: v2.toUpperCase(), better: verdictBetter, isVerdict: true },
        { metric: 'EMI / Income', v1: pct(c1.emi_to_income_ratio), v2: pct(c2.emi_to_income_ratio), better: better(c1.emi_to_income_ratio, c2.emi_to_income_ratio, false) },
        { metric: 'Emergency Runway', v1: (c1.emergency_runway_months || 0).toFixed(1) + ' mo', v2: (c2.emergency_runway_months || 0).toFixed(1) + ' mo', better: better(c1.emergency_runway_months, c2.emergency_runway_months, true) },
        { metric: 'Stress Tests Passed', v1: ss1 + ' / 4', v2: ss2 + ' / 4', better: better(ss1, ss2, true) },
        { metric: 'Monthly Surplus', v1: inr(c1.monthly_surplus_estimate || 0), v2: inr(c2.monthly_surplus_estimate || 0), better: better(c1.monthly_surplus_estimate, c2.monthly_surplus_estimate, true) },
        { metric: 'Monthly EMI', v1: inr(c1.monthly_emi || 0), v2: inr(c2.monthly_emi || 0), better: better(c1.monthly_emi, c2.monthly_emi, false) },
        { metric: 'Price vs Market', v1: (pv1 >= 0 ? '+' : '') + pv1.toFixed(1) + '%', v2: (pv2 >= 0 ? '+' : '') + pv2.toFixed(1) + '%', better: better(pv1, pv2, false) },
        { metric: 'Rent-vs-Buy Break-Even', v1: (c1.rent_vs_buy_break_even_years || 0).toFixed(1) + ' yrs', v2: (c2.rent_vs_buy_break_even_years || 0).toFixed(1) + ' yrs', better: better(c1.rent_vs_buy_break_even_years, c2.rent_vs_buy_break_even_years, false) },
        { metric: 'True Acquisition Cost', v1: inr(c1.true_total_acquisition_cost || c1.total_acquisition_cost || 0), v2: inr(c2.true_total_acquisition_cost || c2.total_acquisition_cost || 0), better: better(c1.true_total_acquisition_cost, c2.true_total_acquisition_cost, false) }
    ];

    const wins1 = rows.filter(r => r.better === '1').length;
    const wins2 = rows.filter(r => r.better === '2').length;
    const overall = wins1 >= wins2 ? '1' : '2';
    const vColors = { safe: 'var(--green)', risky: 'var(--yellow)', reconsider: 'var(--red)' };

    let html = `<table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr>
            <th style="text-align:left;padding:10px 0;color:var(--text-muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border)">Metric</th>
            <th style="text-align:center;padding:10px;color:var(--text-muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border)">${esc(loc1)}</th>
            <th style="text-align:center;padding:10px;color:var(--text-muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border)">${esc(loc2)}</th>
        </tr></thead><tbody>`;

    rows.forEach(row => {
        const c1w = row.better === '1';
        const c2w = row.better === '2';
        html += `<tr>
            <td style="padding:10px 0;color:var(--text-dim);border-bottom:1px solid var(--border)">${esc(row.metric)}</td>
            <td style="text-align:center;padding:10px;border-bottom:1px solid var(--border);font-family:var(--font-mono);color:${row.isVerdict ? (vColors[r1.verdict] || 'var(--text)') : c1w ? 'var(--green)' : 'var(--text)'};font-weight:${c1w ? '700' : '400'}">
                ${esc(row.v1)}${c1w ? ' ✓' : ''}
            </td>
            <td style="text-align:center;padding:10px;border-bottom:1px solid var(--border);font-family:var(--font-mono);color:${row.isVerdict ? (vColors[r2.verdict] || 'var(--text)') : c2w ? 'var(--green)' : 'var(--text)'};font-weight:${c2w ? '700' : '400'}">
                ${esc(row.v2)}${c2w ? ' ✓' : ''}
            </td>
        </tr>`;
    });

    const winnerName = overall === '1' ? esc(loc1) : esc(loc2);
    html += `<tr style="background:rgba(34,197,94,0.07)">
        <td style="padding:12px 0;font-weight:700;color:var(--text)">Overall Recommendation</td>
        <td colspan="2" style="text-align:center;padding:12px;font-weight:700;color:var(--green)">
            ${winnerName} wins on ${overall === '1' ? wins1 : wins2} of ${rows.length} metrics
        </td>
    </tr></tbody></table>`;

    document.getElementById('compare-table-container').innerHTML = html;
    document.getElementById('compare-form').style.display = 'none';
    document.getElementById('compare-results').style.display = 'block';
    document.getElementById('compare-results').scrollIntoView({ behavior: 'smooth' });
}

// --- SHARE & EXPORT ---
function getUserId() {
    let uid = localStorage.getItem('niv_uid');
    if (!uid) { uid = 'anon_' + Date.now(); localStorage.setItem('niv_uid', uid); }
    return uid;
}

async function autoSaveReport(report) {
    try {
        const res = await fetch(`${API}/api/v1/reports`, {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Id': getUserId() },
            body: JSON.stringify({ report: report, input: lastInput })
        });
        if (res.ok) {
            const data = await res.json();
            if (data.id) {
                currentShareUrl = `${window.location.origin}/report/${data.id}`;
                document.getElementById('share-url-input').value = currentShareUrl;
                document.getElementById('share-bar').style.display = 'block';
            }
        }
    } catch (e) { }
}

function copyShareUrl() {
    navigator.clipboard.writeText(currentShareUrl).then(() => {
        const b = document.getElementById('copy-btn'); b.textContent = '✓ Copied';
        setTimeout(() => b.textContent = 'Copy Link', 2000);
    });
}

function shareWhatsApp() {
    if (!currentShareUrl || !lastReport) return;
    const verdict = (lastReport.verdict || 'risky').toUpperCase();
    const location = lastInput?.property?.location_area || 'a property';
    const price = lastInput?.property?.property_price;
    const priceStr = price ? inr(price) : 'a property';
    const emi = lastReport.computed_numbers?.monthly_emi;
    const emiStr = emi ? inr(Math.round(emi)) + '/month EMI' : '';
    const reason = lastReport.verdict_reason || '';
    const msg = [
        `I used Niv AI to analyze ${priceStr} in ${location}.`,
        ``,
        `Verdict: *${verdict}*`,
        emiStr ? `Monthly EMI: ${emiStr}` : '',
        reason ? reason.substring(0, 120) + (reason.length > 120 ? '...' : '') : '',
        ``,
        `Full analysis: ${currentShareUrl}`
    ].filter(Boolean).join('\n');
    window.open(`https://wa.me/?text=${encodeURIComponent(msg)}`, '_blank', 'noopener,noreferrer');
}

function downloadPDF() {
    document.getElementById('print-date').textContent = new Date().toLocaleDateString('en-IN');
    document.getElementById('print-meta').textContent = `${lastInput?.property?.location_area} · ${inr(lastInput?.property?.property_price)}`;
    window.print();
}

function downloadLinkedInCard() {
    if (!lastReport) return;
    const cvs = document.createElement('canvas');
    cvs.width = 1200; cvs.height = 628;
    const ctx = cvs.getContext('2d');

    const BG = '#080810', SURFACE = '#0e0e1a', BORDER = '#1c1c2e';
    const ACCENT = '#7c6af7', GREEN = '#22c55e', YELLOW = '#f59e0b', RED = '#ef4444';
    const TEXT = '#f0eeff', MUTED = '#9896b8';

    const rr = (x, y, w, h, r) => {
        if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); }
        else { ctx.rect(x, y, w, h); }
    };

    // Background
    ctx.fillStyle = BG; ctx.fillRect(0, 0, 1200, 628);

    // Left accent bar
    ctx.fillStyle = ACCENT; ctx.fillRect(0, 0, 6, 628);

    // Header band
    ctx.fillStyle = SURFACE; ctx.fillRect(0, 0, 1200, 120);
    ctx.fillStyle = BORDER; ctx.fillRect(0, 120, 1200, 1);

    ctx.fillStyle = ACCENT; ctx.font = 'bold 18px Arial'; ctx.fillText('NIV AI', 40, 45);
    ctx.fillStyle = MUTED; ctx.font = '14px Arial';
    ctx.fillText('Home Buying Decision Intelligence', 40, 68);
    ctx.fillText('My Financial Stress Test Results', 40, 92);

    // Verdict
    const v = (lastReport.verdict || 'risky').toLowerCase();
    const vColor = v === 'safe' ? GREEN : v === 'reconsider' ? RED : YELLOW;
    ctx.fillStyle = vColor; ctx.font = 'bold 64px Arial';
    ctx.fillText(v.toUpperCase(), 40, 200);

    // Confidence badge
    ctx.fillStyle = BORDER; ctx.beginPath(); rr(40, 215, 200, 32, 6); ctx.fill();
    ctx.fillStyle = MUTED; ctx.font = '14px Arial';
    ctx.fillText('Confidence: ' + (lastReport.confidence_score || '?') + '/10', 55, 236);

    const scenarios = lastReport.stress_scenarios || [];
    const passed = scenarios.filter(s => s.can_survive).length;

    ctx.fillStyle = TEXT; ctx.font = 'bold 22px Arial';
    ctx.fillText('Stress Tests: ' + passed + ' of ' + scenarios.length + ' Survived', 40, 295);

    const scenarioLabels = {
        'job_loss_6_months': 'Job Loss (6 months)',
        'interest_rate_hike_2pct': 'Rate Hike (+2%)',
        'unexpected_expense_5L': 'Emergency ₹5L Expense',
        'income_stagnation_3_years': 'Income Stagnation (3yr)'
    };

    scenarios.forEach((s, i) => {
        const y = 330 + i * 65;
        const color = s.can_survive ? GREEN : RED;
        const label = scenarioLabels[s.name] || (s.name || '').replace(/_/g, ' ');

        ctx.fillStyle = BORDER; ctx.beginPath(); rr(40, y, 500, 48, 6); ctx.fill();
        ctx.fillStyle = color; ctx.beginPath(); rr(40, y, s.can_survive ? 500 : 200, 48, 6); ctx.fill();
        ctx.fillStyle = '#fff'; ctx.font = 'bold 16px Arial';
        ctx.fillText((s.can_survive ? '✓ ' : '✗ ') + label, 56, y + 30);
        ctx.fillStyle = MUTED; ctx.font = '13px Arial';
        ctx.fillText((s.key_number || '').substring(0, 55), 560, y + 30);
    });

    // Right metrics panel
    const emiRatio = lastReport.computed_numbers?.emi_to_income_ratio || 0;
    const runway = lastReport.computed_numbers?.emergency_runway_months || 0;

    ctx.fillStyle = SURFACE; ctx.beginPath(); rr(760, 145, 400, 380, 10); ctx.fill();
    ctx.strokeStyle = BORDER; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = MUTED; ctx.font = 'bold 11px Arial'; ctx.fillText('KEY METRICS', 800, 180);

    const metrics = [
        { label: 'EMI / Income', value: (emiRatio * 100).toFixed(1) + '%', color: emiRatio < 0.30 ? GREEN : emiRatio < 0.45 ? YELLOW : RED },
        { label: 'Emergency Runway', value: runway.toFixed(1) + ' months', color: runway >= 6 ? GREEN : runway >= 3 ? YELLOW : RED },
        { label: 'Stress Tests', value: passed + '/' + scenarios.length, color: passed >= 3 ? GREEN : passed >= 2 ? YELLOW : RED }
    ];

    metrics.forEach((m, i) => {
        const y = 210 + i * 85;
        ctx.fillStyle = BORDER; ctx.beginPath(); rr(790, y, 340, 68, 8); ctx.fill();
        ctx.fillStyle = MUTED; ctx.font = '12px Arial'; ctx.fillText(m.label, 810, y + 24);
        ctx.fillStyle = m.color; ctx.font = 'bold 28px Arial'; ctx.fillText(m.value, 810, y + 56);
    });

    // Footer
    ctx.fillStyle = BORDER; ctx.fillRect(0, 590, 1200, 1);
    ctx.fillStyle = MUTED; ctx.font = '13px Arial';
    ctx.fillText('Niv AI — Home Buying Decision Intelligence', 40, 616);
    ctx.fillText('Analysis for informational purposes only. Not financial advice.', 700, 616);

    const a = document.createElement('a');
    a.download = `niv-ai-stress-test-${Date.now()}.png`;
    a.href = cvs.toDataURL('image/png');
    a.click();
}

// --- OUTCOME TRACKING ---
function maybeShowOutcomePrompt() {
    const createdStr = window.__NIV_REPORT_CREATED__;
    if (!createdStr || localStorage.getItem('outcome_' + window.__NIV_REPORT_ID__)) return;
    const ageDays = Math.floor((new Date() - new Date(createdStr)) / 86400000);
    if (ageDays < 7 || ageDays > 180) return;

    const div = document.createElement('div');
    div.innerHTML = `<div style="position:fixed;bottom:20px;right:20px;background:#0e0e1a;border:1px solid #2a2a40;padding:20px;border-radius:12px;z-index:9999;">
                <p style="margin-bottom:10px;font-size:14px;font-weight:bold;">What did you decide?</p>
                <button onclick="submitOutcome('bought', this)" style="margin:5px;padding:5px 10px;background:#052010;color:#22c55e;border:1px solid #0f3020;border-radius:5px;">Bought it</button>
                <button onclick="submitOutcome('walked_away', this)" style="margin:5px;padding:5px 10px;background:#180808;color:#ef4444;border:1px solid #2a1010;border-radius:5px;">Walked away</button>
                <button onclick="this.parentElement.remove()" style="position:absolute;top:5px;right:10px;background:none;border:none;color:#9896b8;">x</button>
            </div>`;
    document.body.appendChild(div);
}

async function submitOutcome(outcome, btn) {
    const id = window.__NIV_REPORT_ID__;
    if (id) {
        try { await fetch(`${API}/api/v1/reports/${id}/outcome`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ outcome }) }); } catch (e) { }
        localStorage.setItem('outcome_' + id, outcome);
    }
    btn.parentElement.innerHTML = '<p style="color:#22c55e">Thanks for your feedback!</p>';
    setTimeout(() => btn.parentElement?.remove(), 2000);
}

function reset() {
    document.getElementById('report').style.display = 'none';
    document.getElementById('form-section').style.display = 'block';
    ['a1', 'a2', 'a3', 'a4', 'a5', 'a6'].forEach(id => setA(id, 'waiting'));
    window.scrollTo(0, 0);
}

// ─────────────────────────────────────────────────────────────────
// FEATURE 1: COUNTER-OFFER PDF
// ─────────────────────────────────────────────────────────────────
async function downloadCounterOffer() {
    if (!lastReport || !lastInput) return;
    const btn = document.getElementById('counter-offer-btn');
    btn.textContent = '⏳ Generating PDF...';
    btn.disabled = true;
    try {
        const res = await fetch(`${API}/api/v1/tools/counter-offer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ report: lastReport, input: lastInput, buyer_name: 'Home Buyer' })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'PDF generation failed');
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const loc = lastInput?.property?.location_area || 'property';
        a.download = `NIV_AI_Counter_Offer_${loc.replace(/\s+/g, '_')}.pdf`;
        a.href = url;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('Could not generate counter-offer: ' + e.message);
    } finally {
        btn.textContent = '📄 Counter-Offer Letter';
        btn.disabled = false;
    }
}

// ─────────────────────────────────────────────────────────────────
// FEATURE 2: BANK EMAIL GENERATOR
// ─────────────────────────────────────────────────────────────────
let bankEmailContent = null;

function openBankEmailModal() {
    document.getElementById('bank-email-modal').style.display = 'flex';
    document.getElementById('bank-email-content').style.display = 'none';
    document.getElementById('bank-email-loading').style.display = 'none';
    document.getElementById('bank-email-error').style.display = 'none';
    document.getElementById('bank-email-actions').style.display = 'flex';
    bankEmailContent = null;
}

function closeBankEmail() {
    document.getElementById('bank-email-modal').style.display = 'none';
}

async function generateBankEmail() {
    if (!lastReport || !lastInput) return;
    const bank = document.getElementById('target-bank').value;
    document.getElementById('bank-email-loading').style.display = 'block';
    document.getElementById('bank-email-content').style.display = 'none';
    document.getElementById('bank-email-error').style.display = 'none';
    document.getElementById('bank-email-actions').style.display = 'none';
    try {
        const res = await fetch(`${API}/api/v1/tools/bank-email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                computed_numbers: lastReport.computed_numbers || {},
                raw_input: lastInput,
                target_bank: bank
            })
        });
        if (!res.ok) throw new Error('Email generation failed');
        const data = await res.json();
        bankEmailContent = data.full_email_text || '';
        document.getElementById('bank-email-preview').textContent = bankEmailContent;
        document.getElementById('bank-email-loading').style.display = 'none';
        document.getElementById('bank-email-content').style.display = 'block';
        // Show FOIR info
        if (data.foir_pct) {
            const fColor = data.foir_pct < 40 ? 'var(--green)' : data.foir_pct < 50 ? 'var(--yellow)' : 'var(--red)';
            document.getElementById('bank-email-preview').insertAdjacentHTML('beforebegin',
                `<div style="font-size:11px;color:${fColor};margin-bottom:8px;padding:6px 10px;
                 background:var(--bg);border-radius:6px;border-left:2px solid ${fColor}">
                 FOIR: ${data.foir_pct}% ${data.foir_pct < 40 ? '✓ Good' : data.foir_pct < 50 ? '⚠ Borderline' : '✗ High'}
                 — banks prefer FOIR below 40%</div>`
            );
        }
    } catch (e) {
        document.getElementById('bank-email-loading').style.display = 'none';
        document.getElementById('bank-email-error').style.display = 'block';
        document.getElementById('bank-email-error').textContent = 'Failed to generate email: ' + e.message;
        document.getElementById('bank-email-actions').style.display = 'flex';
    }
}

function copyBankEmail() {
    if (!bankEmailContent) return;
    navigator.clipboard.writeText(bankEmailContent).then(() => {
        const btn = document.getElementById('bank-email-copy-btn');
        btn.textContent = '✓ Copied!';
        setTimeout(() => btn.textContent = 'Copy Email', 2000);
    });
}

function openMailto() {
    if (!bankEmailContent) return;
    const subject = encodeURIComponent(`Home Loan Inquiry — ${lastInput?.property?.location_area || 'Property'}`);
    window.location.href = `mailto:?subject=${subject}&body=${encodeURIComponent(bankEmailContent)}`;
}

// ─────────────────────────────────────────────────────────────────
// FEATURE 4: RERA QR SCANNER
// ─────────────────────────────────────────────────────────────────
async function scanReraQR(input) {
    const file = input.files[0];
    if (!file) return;
    const statusEl = document.getElementById('rera-qr-status');
    statusEl.textContent = '⏳ Scanning QR code...';
    statusEl.style.color = 'var(--accent)';

    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch(`${API}/api/v1/documents/scan-rera-qr`, {
            method: 'POST', body: formData
        });
        const data = await res.json();
        if (data.success && data.extracted_rera_number) {
            let msg = `✓ RERA: ${data.extracted_rera_number}`;
            if (data.rera_data?.registration_status === 'active') msg += ' — Active ✓';
            else if (data.rera_data?.risk_label) msg += ` — ${data.rera_data.risk_label}`;
            statusEl.textContent = msg;
            statusEl.style.color = 'var(--green)';
        } else {
            statusEl.textContent = data.error || 'No QR code detected';
            statusEl.style.color = 'var(--red)';
        }
    } catch (e) {
        statusEl.textContent = 'Scan failed — continue manually';
        statusEl.style.color = 'var(--text-muted)';
    }
    input.value = '';
}

// ─────────────────────────────────────────────────────────────────
// FEATURE 5: MARKET RATES
// ─────────────────────────────────────────────────────────────────
async function loadMarketRates() {
    const banner = document.getElementById('market-rates-banner');
    const textEl = document.getElementById('market-rates-text');
    if (!banner) return;
    banner.style.display = 'flex';
    textEl.textContent = 'Loading current rates...';
    try {
        const userRate = getNum('expected_interest_rate') || null;
        const url = userRate ? `${API}/api/v1/market/rates?user_rate=${userRate}` : `${API}/api/v1/market/rates`;
        const res = await fetch(url);
        if (!res.ok) throw new Error('rates unavailable');
        const data = await res.json();
        marketRatesData = data;
        textEl.textContent = `Market rates: ${data.market_floor}%–${data.market_ceiling}% · RBI Repo: ${data.rbi_repo_rate}% · Source: ${data.data_source}`;
        if (userRate) updateRateWarning(userRate, data);
    } catch (e) {
        textEl.textContent = 'Live rates unavailable — using Apr 2026 benchmarks (8.50–9.90%)';
    }
}

function updateRateWarning(userRate, ratesData) {
    const banner = document.getElementById('market-rates-banner');
    const textEl = document.getElementById('market-rates-text');
    if (!banner || !ratesData) return;
    if (ratesData.rate_warning || (userRate && ratesData.market_floor && userRate < ratesData.market_floor)) {
        const gap = Math.round((ratesData.market_floor - userRate) * 100);
        textEl.innerHTML = `<span style="color:var(--yellow)">⚠ Your rate (${userRate}%) is ${gap}bps below market floor (${ratesData.market_floor}%). EMI may be higher than estimated.</span>`;
    } else {
        textEl.textContent = `Market rates: ${ratesData.market_floor}%–${ratesData.market_ceiling}% · RBI Repo: ${ratesData.rbi_repo_rate}%`;
    }
}

function refreshMarketRates() { marketRatesData = null; loadMarketRates(); }

// ─────────────────────────────────────────────────────────────────
// FEATURE 7 & 8: DOCUMENT UPLOAD (EC + LOAN LETTER)
// ─────────────────────────────────────────────────────────────────
async function uploadEC(input) {
    const file = input.files[0];
    if (!file) return;
    const zone = input.closest('.doc-upload-zone') || input.parentElement;
    zone.classList.add('uploading');
    const resultDiv = document.getElementById('ec-result');
    resultDiv.innerHTML = '<div style="font-size:11px;color:var(--accent);margin-top:8px">⏳ Analyzing EC...</div>';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('location_area', lastInput?.property?.location_area || 'Unknown');
    formData.append('property_price', String(lastInput?.property?.property_price || 0));

    try {
        const res = await fetch(`${API}/api/v1/documents/parse-ec`, { method: 'POST', body: formData });
        const data = await res.json();
        zone.classList.remove('uploading');
        if (data.success && data.analysis) {
            const a = data.analysis;
            const riskClass = a.risk_level || 'caution';
            const riskColor = { clear: 'var(--green)', caution: 'var(--yellow)', high_risk: 'var(--red)' }[riskClass] || 'var(--text-muted)';
            const mortgages = (a.mortgages || []).filter(m => m.status !== 'discharged');
            resultDiv.innerHTML = `
                <div class="doc-result-card ${riskClass}">
                    <div style="font-weight:700;color:${riskColor};font-size:12px;margin-bottom:6px;text-transform:uppercase">
                        ${riskClass.replace('_', ' ')} — ${a.has_encumbrances ? 'Encumbrances Found' : 'No Active Encumbrances'}
                    </div>
                    <div style="color:var(--text-dim);font-size:12px;margin-bottom:8px">${esc(a.summary || '')}</div>
                    ${mortgages.length > 0 ? `<div style="color:var(--red);font-size:11px">⚠ Active mortgages: ${mortgages.map(m => esc(m.lender)).join(', ')}</div>` : ''}
                    ${(a.legal_disputes || []).length > 0 ? `<div style="color:var(--red);font-size:11px">⚠ Legal dispute on record</div>` : ''}
                    <div style="color:var(--text-muted);font-size:11px;margin-top:6px;font-style:italic">${esc(a.recommendation || '')}</div>
                </div>`;
        } else {
            resultDiv.innerHTML = `<div style="color:var(--red);font-size:11px;margin-top:8px">✗ ${esc(data.error || 'Analysis failed')}</div>`;
        }
    } catch (e) {
        zone.classList.remove('uploading');
        resultDiv.innerHTML = '<div style="color:var(--red);font-size:11px;margin-top:8px">✗ Upload failed. Try again.</div>';
    }
    input.value = '';
}

async function uploadLoanLetter(input) {
    const file = input.files[0];
    if (!file) return;
    const zone = input.closest('.doc-upload-zone') || input.parentElement;
    zone.classList.add('uploading');
    const resultDiv = document.getElementById('loan-result');
    resultDiv.innerHTML = '<div style="font-size:11px;color:var(--accent);margin-top:8px">⏳ Extracting loan terms...</div>';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`${API}/api/v1/documents/parse-loan-letter`, { method: 'POST', body: formData });
        const data = await res.json();
        zone.classList.remove('uploading');
        if (data.success && data.data) {
            const d = data.data;
            const hasAutoFill = d.auto_fill?.loan_tenure_years || d.auto_fill?.interest_rate;
            resultDiv.innerHTML = `
                <div class="doc-result-card">
                    <div style="font-weight:700;color:var(--green);font-size:12px;margin-bottom:8px">
                        ✓ ${esc(d.bank_name || 'Bank')} Loan Letter Parsed
                    </div>
                    <table style="width:100%;font-size:11px;border-collapse:collapse">
                        ${d.sanctioned_amount ? `<tr><td style="color:var(--text-muted);padding:2px 0">Sanctioned Amount</td><td style="color:var(--text);text-align:right">${inr(d.sanctioned_amount)}</td></tr>` : ''}
                        ${d.interest_rate_pct ? `<tr><td style="color:var(--text-muted);padding:2px 0">Interest Rate</td><td style="color:var(--text);text-align:right">${d.interest_rate_pct}% (${d.rate_type || 'unknown'})</td></tr>` : ''}
                        ${d.loan_tenure_years ? `<tr><td style="color:var(--text-muted);padding:2px 0">Tenure</td><td style="color:var(--text);text-align:right">${d.loan_tenure_years} years</td></tr>` : ''}
                        ${d.processing_fee ? `<tr><td style="color:var(--yellow);padding:2px 0">Processing Fee</td><td style="color:var(--yellow);text-align:right">${inr(d.processing_fee)}</td></tr>` : ''}
                        ${(d.hidden_charges || []).length > 0 ? `<tr><td colspan="2" style="color:var(--red);padding:4px 0;font-size:10px">⚠ Hidden charges: ${d.hidden_charges.map(h => esc(h)).join(' · ')}</td></tr>` : ''}
                    </table>
                    ${hasAutoFill ? `<button onclick="applyLoanAutoFill(${JSON.stringify(d.auto_fill || {}).replace(/"/g, '&quot;')})"
                        style="margin-top:10px;width:100%;padding:8px;background:var(--accent-dim);
                        border:1px solid var(--accent);border-radius:6px;color:var(--accent);
                        font-size:11px;cursor:pointer">
                        Apply to Form →
                    </button>` : ''}
                    ${d.sanctioned_amount && lastInput?.property?.property_price ?
                        `<div style="font-size:11px;color:var(--text-muted);margin-top:6px">
                        Down Payment Needed: ${inr(Math.max(0, lastInput.property.property_price - d.sanctioned_amount))}
                        </div>` : ''}
                </div>`;
        } else {
            resultDiv.innerHTML = `<div style="color:var(--red);font-size:11px;margin-top:8px">✗ ${esc(data.error || 'Extraction failed')}</div>`;
        }
    } catch (e) {
        zone.classList.remove('uploading');
        resultDiv.innerHTML = '<div style="color:var(--red);font-size:11px;margin-top:8px">✗ Upload failed. Try again.</div>';
    }
    input.value = '';
}

function applyLoanAutoFill(autoFill) {
    if (autoFill.interest_rate) {
        const el = document.getElementById('expected_interest_rate');
        if (el) { el.value = autoFill.interest_rate; updateEMIPreview(); }
    }
    if (autoFill.loan_tenure_years) {
        const el = document.getElementById('loan_tenure_years');
        if (el) { el.value = autoFill.loan_tenure_years; updateEMIPreview(); }
    }
    alert('Loan terms applied to form! Review and re-run analysis if needed.');
}

// ─────────────────────────────────────────────────────────────────
// FEATURE 9: GST HEALTH CHECK
// ─────────────────────────────────────────────────────────────────
async function checkBuilderGST() {
    const gstin = (document.getElementById('builder_gstin')?.value || '').trim().toUpperCase();
    const resultDiv = document.getElementById('gst-result');
    const btn = document.getElementById('gst-check-btn');
    if (!gstin || gstin.length !== 15) {
        resultDiv.textContent = 'Enter 15-character GSTIN first';
        resultDiv.style.color = 'var(--text-muted)';
        return;
    }
    btn.textContent = '...';
    btn.disabled = true;
    try {
        const res = await fetch(`${API}/api/v1/tools/gst-check?gstin=${encodeURIComponent(gstin)}`);
        if (res.status === 422) {
            resultDiv.textContent = 'Invalid GSTIN format';
            resultDiv.style.color = 'var(--red)';
            return;
        }
        const data = await res.json();
        if (data.risk_flag) {
            resultDiv.innerHTML = `<span style="color:var(--red)">✗ Risk — ${esc(data.risk_explanation)}</span>`;
        } else if (data.registration_status === 'active') {
            const filed = data.last_return_filed ? ` · Filed ${data.last_return_filed}` : '';
            resultDiv.innerHTML = `<span style="color:var(--green)">✓ Active${filed}</span>`;
        } else {
            resultDiv.innerHTML = `<span style="color:var(--text-muted)">${esc(data.risk_explanation)}</span>`;
        }
    } catch (e) {
        resultDiv.textContent = 'Verification unavailable';
        resultDiv.style.color = 'var(--text-muted)';
    } finally {
        btn.textContent = 'Verify GST';
        btn.disabled = false;
    }
}

// ─────────────────────────────────────────────────────────────────
// FEATURE 10: OC/CC STATUS RENDER
// ─────────────────────────────────────────────────────────────────
function renderOcCcStatus(occc) {
    if (!occc) return '';
    const colorMap = {
        low: 'var(--green)', medium: 'var(--yellow)',
        high: 'var(--red)', critical: 'var(--red)'
    };
    const color = colorMap[occc.risk_level] || 'var(--text-muted)';
    const label = (occc.risk_level || 'unknown').toUpperCase();
    return `
        <div style="margin-top:12px;padding:12px;background:var(--bg);
             border-radius:8px;border-left:3px solid ${color}">
            <div style="font-size:11px;font-weight:700;color:${color};
                 text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">
                OC/CC Status: ${label}
            </div>
            <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">
                ${esc(occc.overall_note || '')}
            </div>
            ${(occc.risk_flags || []).map(f =>
                `<div style="font-size:11px;color:var(--yellow);margin-top:3px">⚠ ${esc(f)}</div>`
            ).join('')}
        </div>`;
}

// ─────────────────────────────────────────────────────────────────
// INIT ---
document.addEventListener('DOMContentLoaded', () => {
    updateFinancialHealth();

    if (window.__NIV_PRELOADED_REPORT__) {
        lastReport = window.__NIV_PRELOADED_REPORT__;
        document.getElementById('form-section').style.display = 'none';
        renderReport(lastReport);
        document.getElementById('report').style.display = 'block';

        if (window.__NIV_SHARED_MODE__) {
            const banner = document.createElement('div');
            banner.style.cssText = [
                'background:rgba(124,106,247,0.1)',
                'border:1px solid var(--accent-dim)',
                'border-radius:10px',
                'padding:12px 16px',
                'margin-bottom:16px',
                'font-size:13px',
                'color:var(--text-dim)',
                'text-align:center'
            ].join(';');
            banner.innerHTML = 'This is a shared analysis. '
                + '<a href="/" style="color:var(--accent);font-weight:600">Run your own →</a>';
            document.getElementById('report').prepend(banner);
            setTimeout(maybeShowOutcomePrompt, 3000);
        }
    }
});