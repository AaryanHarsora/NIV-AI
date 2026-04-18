// 8. SESSION ACTIONS
// ════════════════════════════════════════════════════
async function startSession() {
  if (isSubmitting) return;
  isSubmitting = true;
  const btn = document.getElementById('btn-enter');
  btn.disabled = true;
  btn.textContent = '⟳ Initializing...';
  showLoading('Initializing Session', 'POST /session/start');

  try {
    const data = await apiPost('/session/start', {});
    session_id = data.session_id;
  } catch (err) {
    session_id = 'local-' + Math.random().toString(36).slice(2,10).toUpperCase();
    showToast(`Backend offline — local session: ${session_id.slice(0,12)}`);
  }

  hideLoading();
  isSubmitting = false;
  btn.disabled = false;
  btn.textContent = '⟶ Initialize Fiduciary Session';
  transitionTo(STATES.BEHAVIORAL);
}

async function submitBehavioral(answer) {
  if (isSubmitting) return;
  isSubmitting = true;
  behavioralAnswers = [{ question_id: 'fomo_1', answer }];
  showLoading('Profiling Behavior', 'POST /behavioral/' + session_id);
  try {
    await apiPost(`/behavioral/${session_id}`, { answers: behavioralAnswers });
  } catch (err) {
    console.warn('Behavioral endpoint (non-blocking):', err.message);
  }
  hideLoading();
  isSubmitting = false;
  transitionTo(STATES.INPUT);
}

function getFormValues() {
  return {
    monthly_income:       parseFloat(document.getElementById('f-income').value) || null,
    monthly_expenses:     parseFloat(document.getElementById('f-expenses').value) || null,
    total_savings:        parseFloat(document.getElementById('f-savings').value) || null,
    property_price:       parseFloat(document.getElementById('f-price').value) || null,
    down_payment:         parseFloat(document.getElementById('f-down').value) || null,
    tenure_years:         parseInt(document.getElementById('f-tenure').value) || null,
    annual_interest_rate: parseFloat(document.getElementById('f-rate').value) || null,
    age:                  parseInt(document.getElementById('f-age').value) || null,
    state:                document.getElementById('f-state').value || null,
    property_type:        document.getElementById('f-ptype').value || null,
  };
}

function validateInput(vals) {
  const errors = [];
  if (!vals.monthly_income || vals.monthly_income <= 0) errors.push('Monthly income is required');
  if (vals.monthly_expenses === null || vals.monthly_expenses < 0) errors.push('Monthly expenses required');
  if (vals.total_savings === null || vals.total_savings < 0) errors.push('Total savings required');
  if (!vals.property_price || vals.property_price < 100000) errors.push('Property price must be ≥ ₹1L');
  if (vals.down_payment === null || vals.down_payment < 0) errors.push('Down payment required');
  if (!vals.tenure_years || vals.tenure_years < 1 || vals.tenure_years > 30) errors.push('Tenure must be 1–30 years');
  if (!vals.annual_interest_rate || vals.annual_interest_rate < 1) errors.push('Interest rate required');
  if (!vals.age || vals.age < 18 || vals.age > 65) errors.push('Age must be 18–65');
  if (!vals.state) errors.push('State / UT is required');
  if (!vals.property_type) errors.push('Property type is required');
  return errors;
}

async function submitAnalysis() {
  if (isSubmitting) return;
  const vals = getFormValues();
  const errors = validateInput(vals);
  if (errors.length > 0) { showToast('⚠ ' + errors[0]); return; }

  isSubmitting = true;
  userInput = { ...vals };
  const btn = document.getElementById('btn-analyze');
  btn.disabled = true;
  btn.textContent = '⟳ Submitting...';
  showLoading('Submitting Parameters', 'POST /analyze/' + session_id);

  try {
    const data = await apiPost(`/analyze/${session_id}`, userInput);
    backendResults = data;
  } catch (err) {
    console.warn('Analyze endpoint — using local computation:', err.message);
    backendResults = computeLocalResults(userInput);
    showToast('Backend offline — local computation engine active');
  }

  hideLoading();
  isSubmitting = false;
  btn.disabled = false;
  btn.textContent = '⟶ Run Multi-Agent Analysis';
  transitionTo(STATES.LOADING);
  startRoundtable();
}

// ════════════════════════════════════════════════════
