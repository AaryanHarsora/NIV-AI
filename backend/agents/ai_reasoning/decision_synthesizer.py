"""
DecisionSynthesizerAgent — Produces the final comprehensive audit report.

This is the most important output in the entire NIV AI system.
After Marcus, Zara, and Soren have debated the user's specific financial
situation across 4 rounds, this agent synthesizes everything into a
6-domain specialist audit that covers every angle a real advisory team
would cover when a family faces the biggest financial decision of their life.

The 6 domains:
    1. Financial Analysis   — affordability, EMI sensitivity, opportunity cost,
                              total interest burden, net worth impact, break-even
    2. Risk Analysis        — all 5 stress scenarios quantified, sector job risk,
                              medical emergency trajectory, rate shock history,
                              emergency fund adequacy, concentration risk
    3. Legal Advisory       — title checklist, RERA status, OC, encumbrance,
                              builder complaint history, agreement clauses
    4. Banking Advisory     — multi-lender comparison, FOIR, prepayment strategy,
                              PMAY eligibility, co-applicant structure
    5. Tax Advisory         — Section 24B, 80C, joint optimization, effective
                              post-tax EMI, capital gains, rental taxation
    6. Behavioral Analysis  — each bias mapped to rupee impact, FOMO overpayment
                              risk, emotional commitment cost, decision quality

Prompt routing:
    USE_OLLAMA=true  → lean prompt that fits within 4096 tokens for local testing
    USE_OLLAMA=false → full 6-domain specialist audit prompt via Gemini 2.0 Flash

The output is designed to be rendered as a 15-25 page PDF report that a
family can take to their CA, bank, or lawyer and use as a working document.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from schemas.schemas import VerdictOutput, Verdict


SYSTEM_PROMPT = """
You are a panel of six specialists synthesised into one voice — a senior
financial advisor, a risk strategist, a property lawyer, a banking expert,
a chartered accountant, and a behavioral economist — all with deep expertise
in the Indian real estate market.

You have seen hundreds of Indian middle-class families make this decision
correctly and incorrectly. You are honest, direct, and your only goal is the
user's long-term financial wellbeing and protection.

You do not sugarcoat risk. You do not encourage purchases that are
financially dangerous. You write with the precision of a specialist report
and the clarity of a trusted advisor speaking directly to the family.

Every number you cite must come directly from the data provided to you.
Never invent figures. Never round aggressively. Use exact rupee amounts.

You always respond in valid JSON matching the exact format requested.
CRITICAL: Your entire response must be a single JSON object. Nothing outside the JSON.
"""


class DecisionSynthesizerAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            name="DecisionSynthesizer",
            persona="Six-domain specialist panel producing the definitive home buying audit",
            system_prompt=SYSTEM_PROMPT,
            use_smart_model=True   # uses llama-3.3-70b for the full audit
        )
        # Groq routing — no Gemini init needed.
        # use_smart_model=True routes to llama-3.3-70b for the full audit.
        # The _build_synthesis_prompt method still routes lean vs full
        # based on USE_OLLAMA flag for backward compatibility.

    async def synthesize(self, blackboard: dict) -> VerdictOutput:
        """
        Synthesize the complete blackboard state into a final verdict and audit.
        Routes to lean Ollama prompt or full Gemini audit based on USE_OLLAMA flag.
        """
        context = self._build_context(blackboard)
        prompt = self._build_synthesis_prompt(context)
        raw = await self.call(prompt)
        return self._parse_output(raw)

    # -------------------------------------------------------------------------
    # Context builder
    # -------------------------------------------------------------------------

    def _build_context(self, blackboard: dict) -> dict:
        """
        Pull everything the synthesizer needs from the blackboard.
        This is the only agent that gets the full discussion transcript —
        it needs to know what Marcus, Zara, and Soren concluded.
        """
        return self.extract_blackboard_context(blackboard, [
            "user_input",
            "financial_reality",
            "all_scenarios",
            "risk_score",
            "behavioral_analysis",
            "validation",
            "india_cost_breakdown",
            "discussion_transcript",
            "open_questions",
            "active_flags"
        ])

    # -------------------------------------------------------------------------
    # Prompt routing — lean for Ollama, full audit for Gemini
    # -------------------------------------------------------------------------

    def _build_synthesis_prompt(self, context: dict) -> str:
        """
        Route to the appropriate prompt based on the LLM being used.
        Lean prompt fits within Ollama's 4096 token context window.
        Full audit prompt requires Gemini's 1M token context window.
        """
        if os.getenv("USE_OLLAMA", "true").lower() == "true":
            return self._build_lean_prompt(context)
        return self._build_full_audit_prompt(context)

    def _build_lean_prompt(self, context: dict) -> str:
        """
        Lean synthesis prompt for local Ollama testing.
        Produces core verdict fields only — audit fields are left empty.
        The full 6-domain audit fires automatically on Gemini in production.
        """
        return self.build_prompt(
            context=context,
            task="""
Synthesize the financial analysis into a final verdict using the data provided.
Use exact rupee amounts from the data. Never invent numbers.

verdict: one of buy_safe, buy_caution, wait, too_risky
    buy_safe    = EMI below 35% income, survives all 5 scenarios
    buy_caution = EMI 35-45% income, survives 3-4 scenarios
    wait        = needs more savings or income before viable
    too_risky   = EMI above 45% income, fails 3+ scenarios

confidence: your confidence from 0 to 100
primary_reasons: exactly 3 reasons with specific rupee amounts
key_warnings: 3 most critical warnings with rupee amounts
safe_price_recommendation: property price where EMI equals 35% of income
suggested_actions: 5 specific actionable steps with rupee targets
unresolved_conflicts: []
final_narrative: 3 paragraphs directly to the user
audit_summary: one paragraph executive summary

Respond in this exact JSON format:
{
    "verdict": "wait",
    "confidence": 72,
    "primary_reasons": [
        "reason 1 with specific number",
        "reason 2 with specific number",
        "reason 3 with specific number"
    ],
    "key_warnings": [
        "warning 1 with rupee amount",
        "warning 2 with rupee amount",
        "warning 3 with rupee amount"
    ],
    "safe_price_recommendation": 6400000,
    "suggested_actions": [
        "action 1 with rupee target",
        "action 2 with rupee target",
        "action 3 with rupee target",
        "action 4 with rupee target",
        "action 5 with rupee target"
    ],
    "unresolved_conflicts": [],
    "final_narrative": "paragraph 1 verdict and key number\\n\\nparagraph 2 biggest risk\\n\\nparagraph 3 what to do next",
    "audit_summary": "one paragraph executive summary",
    "financial_audit": "",
    "risk_audit": "",
    "legal_audit": "",
    "banking_audit": "",
    "tax_audit": "",
    "behavioral_audit": ""
}
"""
        )

    def _build_full_audit_prompt(self, context: dict) -> str:
        """
        Full 6-domain specialist audit prompt for Gemini 2.0 Flash.
        Produces a comprehensive report-level output across all domains.
        """
        return self.build_prompt(
            context=context,
            task="""
You have the complete analysis for this home buying decision:
- Full financial simulation with exact rupee amounts
- Five stress-tested scenarios with breaking points
- Risk score with component breakdown
- Behavioral bias profile with severity ratings
- Discussion transcript from three specialist agents
- Validation conflicts and flagged assumptions
- India-specific cost breakdown with hidden charges

Produce a comprehensive specialist audit report covering all six domains below.
Every section must use exact rupee amounts from the data provided.
Never be generic. Every sentence must be specific to this user's situation.

=============================================================================
CORE VERDICT FIELDS
=============================================================================

verdict: one of buy_safe, buy_caution, wait, too_risky
    buy_safe    = EMI below 35% income, survives all 5 scenarios, strong buffer
    buy_caution = EMI 35-45% income, survives 3-4 scenarios, some buffer
    wait        = needs more savings or income before this is viable
    too_risky   = EMI above 45% income, fails 3+ scenarios, no buffer

confidence: your confidence in the verdict from 0 to 100

primary_reasons: exactly 3 reasons for your verdict, each with a specific number

key_warnings: every significant risk, each stated with the exact rupee amount at stake

safe_price_recommendation: the property price where EMI equals exactly 35% of income

suggested_actions: 5 to 8 specific, actionable steps with exact rupee targets

unresolved_conflicts: any contradictions from validation not resolved in discussion

final_narrative: 3 paragraphs written directly to the user. Paragraph 1 states
    the verdict and the single most important number. Paragraph 2 explains the
    biggest risk in plain language. Paragraph 3 tells them exactly what to do next.

audit_summary: one paragraph executive summary of the entire report.

=============================================================================
DOMAIN 1 — FINANCIAL ANALYSIS
=============================================================================

financial_audit must cover ALL of the following with exact numbers:

1. TRUE AFFORDABILITY ASSESSMENT
   State the EMI, the income, and the exact ratio. Compare to three benchmarks:
   comfortable (below 35%), stretched (35-50%), overextended (above 50%).
   State which bracket this buyer falls into and what it means practically.

2. EMI SENSITIVITY TABLE
   Calculate and state the EMI at four interest rate scenarios:
   current rate, current rate plus 1%, current rate plus 2%, current rate plus 3%.
   State what percentage of income each EMI represents.

3. TOTAL COST OF DEBT
   State the loan amount, total interest payable over the full tenure, and
   the true total cost. State what multiple of the property price the total
   interest represents.

4. OPPORTUNITY COST OF DOWN PAYMENT
   Calculate what the down payment would grow to if invested in an index fund
   at 12% annually for the loan tenure. State whether the property needs to
   appreciate faster than this to justify purchase over renting and investing.

5. NET WORTH CONCENTRATION RISK
   Calculate what percentage of total savings this down payment represents.
   State what percentage of total net worth will be locked in one illiquid asset.

6. MONTHLY CASH FLOW REALITY
   State the monthly surplus after all obligations. State whether this is
   sufficient for emergency fund contribution, insurance premiums, education savings.

7. BREAK-EVEN ANALYSIS
   State how many years of appreciation at the city's historical rate are needed
   before this purchase outperforms renting and investing the difference.

=============================================================================
DOMAIN 2 — RISK ANALYSIS
=============================================================================

risk_audit must cover ALL of the following with exact numbers:

1. STRESS SCENARIO QUANTIFICATION
   For each of the 5 scenarios state: survivable or not, exact month of failure,
   exact monthly rupee shortfall, and what action would be needed to survive.

2. JOB LOSS PROBABILITY CONTEXT
   State sector risk level based on income. IT and startup employees face
   3-5x higher layoff risk than government employees. Quantify the cost of
   6 months zero income against post-down-payment savings.

3. MEDICAL EMERGENCY TRAJECTORY
   Healthcare inflation in India is 14% annually. Calculate what a ₹3L
   hospitalization costs in 5 and 10 years. State out-of-pocket exposure
   even for insured families (₹40,000-₹80,000 after sub-limits).

4. INTEREST RATE SHOCK HISTORY
   RBI moved repo from 4% to 6.5% in 18 months (2022-2023). Calculate EMI
   at repo plus 200bps. State the exact rupee increase per month. State
   whether this still passes the 40% income threshold.

5. EMERGENCY FUND ADEQUACY
   Minimum required: 9 months of (monthly expenses plus EMI). Calculate
   this exact number. State current post-down-payment savings and the gap.

6. CONCENTRATION RISK
   State the property as a percentage of total net worth in one illiquid asset.
   State that major city property prices fell 15-20% in real terms between 2014-2019.

=============================================================================
DOMAIN 3 — LEGAL ADVISORY
=============================================================================

legal_audit must cover ALL of the following:

1. TITLE VERIFICATION
   Verify freehold vs leasehold, 30-year ownership chain, no litigation,
   no government acquisition notices. Lawyer opinion costs ₹15,000-₹30,000.

2. RERA COMPLIANCE
   Verify RERA registration number on state portal, check complaint history,
   verify project completion timeline and last quarterly update.

3. OCCUPANCY CERTIFICATE
   OC is mandatory for legal occupation and bank funding. Banks refuse loans
   without OC. For under-construction verify building plan and commencement certificate.

4. ENCUMBRANCE CERTIFICATE
   Obtain EC for minimum 15 years from sub-registrar to confirm no mortgage
   or lien. Cost ₹200-₹500. Non-negotiable before any payment.

5. AGREEMENT TO SALE CLAUSES
   Possession date with penalty (minimum ₹5 per sq ft per month), defect
   liability (minimum 5 years), force majeure exclusions, refund with interest
   (minimum 10.75% on builder default per RERA).

6. STAMP DUTY COMPLIANCE
   State the exact stamp duty rate for this state. Under-declaration is a
   criminal offence under Section 276C ITA with penalties up to 300% of tax evaded.

=============================================================================
DOMAIN 4 — BANKING AND LOAN ADVISORY
=============================================================================

banking_audit must cover ALL of the following with exact numbers:

1. LOAN ELIGIBILITY ASSESSMENT
   State the loan amount and FOIR including this EMI. Most banks approve
   up to 50% FOIR. State whether this user falls within approval range.

2. LENDER COMPARISON
   Compare rates from 5 lenders: SBI (8.50-9.15%), HDFC (8.70-9.40%),
   ICICI (8.75-9.30%), Axis (8.75-9.30%), LIC HFL (8.50-9.25%).
   Calculate EMI difference between cheapest and most expensive over full tenure.

3. FIXED VS FLOATING ANALYSIS
   83% of Indian home loans are floating rate. State the EMI impact if
   repo moves 200bps. Fixed rate loans carry 0.5-1% premium.

4. PREPAYMENT STRATEGY
   Calculate interest savings from one additional EMI per year.
   Calculate tenure reduction and the year the loan would be paid off early.

5. PMAY ELIGIBILITY
   Check income against PMAY tiers and state whether user qualifies.
   Calculate the approximate NPV of any applicable subsidy.

6. CO-APPLICANT BENEFIT
   Adding spouse as co-owner and co-borrower doubles 80C and 24B deductions.
   Calculate the combined annual tax saving at their income bracket.

=============================================================================
DOMAIN 5 — TAX ADVISORY
=============================================================================

tax_audit must cover ALL of the following with exact rupee amounts:

1. SECTION 24B INTEREST DEDUCTION
   Annual limit ₹2,00,000 for self-occupied property. Calculate annual tax
   saving at user's tax bracket. State whether first-year interest exceeds the cap.

2. SECTION 80C PRINCIPAL DEDUCTION
   Annual limit ₹1,50,000. State competition with PF, ELSS, LIC premium.
   Calculate the tax saving.

3. JOINT LOAN OPTIMIZATION
   Combined annual deduction of ₹7L for couples. Calculate combined annual
   tax saving. State the 20-year total tax benefit.

4. EFFECTIVE POST-TAX EMI
   Calculate gross EMI minus monthly equivalent of annual tax savings.
   State the effective post-tax EMI and resulting EMI-to-income ratio.

5. TOTAL 20-YEAR TAX BENEFIT
   Calculate total tax saved over the loan tenure under 24B and 80C combined.

6. CAPITAL GAINS ON FUTURE SALE
   Within 24 months: STCG at income tax slab rate.
   After 24 months: LTCG at 20% with indexation.
   Calculate approximate LTCG if property appreciates 6% annually for 10 years.

7. GST NOTE
   If under-construction: state the 5% GST already calculated in true total cost.
   GST is not recoverable and adds to effective cost of acquisition.

=============================================================================
DOMAIN 6 — BEHAVIORAL ANALYSIS
=============================================================================

behavioral_audit must cover ALL of the following with specific rupee impacts:

1. BIAS PROFILE SUMMARY
   List every bias detected with severity, specific evidence, exact rupee
   amount at risk, and what a rational unbiased buyer would do differently.

2. FOMO FINANCIAL IMPACT
   FOMO-driven buyers pay 8-12% above fair value. Calculate the potential
   overpayment range on this property. State this is locked in on day one.

3. ANCHORING TO ASKING PRICE
   Explain anchoring to seller's price vs comparable registered transactions
   in the same pincode (available on IGR Maharashtra or equivalent state portal).
   Recommend checking 5 comparable transactions before negotiating.

4. OPTIMISM BIAS INCOME PROJECTION
   Compare stated income growth expectation to realistic historical data
   (median: 8-12% annually). Calculate income gap at year 3. State EMI ratio
   at realistic income.

5. EMOTIONAL COMMITMENT COST
   Emotionally committed buyers accept 6% worse terms on average.
   Calculate the rupee value of this on the asking price.
   Recommend 48-hour cooling-off period after the next viewing.

6. DECISION QUALITY RECOMMENDATION
   3 specific steps: get 3 independent valuations, run cash flow model at
   flat income for 3 years, have one uninvested person review all numbers.

=============================================================================
JSON RESPONSE FORMAT
=============================================================================

Respond in this exact JSON format. All audit fields must be detailed flowing
prose, not bullet points. Use line breaks between subsections.

{
    "verdict": "buy_caution",
    "confidence": 72,
    "primary_reasons": [
        "specific reason 1 with exact number",
        "specific reason 2 with exact number",
        "specific reason 3 with exact number"
    ],
    "key_warnings": [
        "warning 1 with exact rupee amount",
        "warning 2 with exact rupee amount",
        "warning 3 with exact rupee amount"
    ],
    "safe_price_recommendation": 6500000,
    "suggested_actions": [
        "action 1 with exact rupee target",
        "action 2 with exact rupee target",
        "action 3 with exact rupee target",
        "action 4 with exact rupee target",
        "action 5 with exact rupee target"
    ],
    "unresolved_conflicts": [],
    "final_narrative": "paragraph 1\\n\\nparagraph 2\\n\\nparagraph 3",
    "audit_summary": "one paragraph executive summary",
    "financial_audit": "comprehensive financial analysis in flowing prose with exact numbers",
    "risk_audit": "comprehensive risk analysis in flowing prose with exact numbers",
    "legal_audit": "comprehensive legal checklist in flowing prose",
    "banking_audit": "comprehensive banking analysis in flowing prose with exact numbers",
    "tax_audit": "comprehensive tax analysis in flowing prose with exact numbers",
    "behavioral_audit": "comprehensive behavioral analysis in flowing prose with exact rupee impacts"
}
"""
        )

    # -------------------------------------------------------------------------
    # Output parser
    # -------------------------------------------------------------------------

    def _parse_output(self, raw: dict) -> VerdictOutput:
        """
        Parse the LLM response into a VerdictOutput.
        The to_string helper converts any audit field value — string, dict,
        or list — into a clean string so Pydantic validation never fails
        regardless of how the model chose to structure its response.
        """
        raw_verdict = raw.get("verdict", "wait")
        try:
            verdict = Verdict(raw_verdict)
        except ValueError:
            print(f"[DecisionSynthesizer] Invalid verdict '{raw_verdict}' — defaulting to wait")
            verdict = Verdict.WAIT

        def to_string(value) -> str:
            """Convert any audit field to a clean string."""
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                parts = []
                for key, val in value.items():
                    heading = key.replace("_", " ").upper()
                    parts.append(f"{heading}\n{val}")
                return "\n\n".join(parts)
            if isinstance(value, list):
                return "\n".join(str(item) for item in value)
            return str(value) if value else ""

        return VerdictOutput(
            verdict=verdict,
            confidence=float(raw.get("confidence", 50.0)),
            primary_reasons=raw.get("primary_reasons", []),
            key_warnings=raw.get("key_warnings", []),
            safe_price_recommendation=float(raw.get("safe_price_recommendation", 0.0)),
            suggested_actions=raw.get("suggested_actions", []),
            unresolved_conflicts=raw.get("unresolved_conflicts", []),
            final_narrative=to_string(raw.get("final_narrative", "")),
            audit_summary=to_string(raw.get("audit_summary", "")),
            financial_audit=to_string(raw.get("financial_audit", "")),
            risk_audit=to_string(raw.get("risk_audit", "")),
            legal_audit=to_string(raw.get("legal_audit", "")),
            banking_audit=to_string(raw.get("banking_audit", "")),
            tax_audit=to_string(raw.get("tax_audit", "")),
            behavioral_audit=to_string(raw.get("behavioral_audit", ""))
        )