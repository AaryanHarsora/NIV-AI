from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


# Enums

class AffordabilityStatus(str, Enum):
    COMFORTABLE = "comfortable"
    STRETCHED = "stretched"
    OVEREXTENDED = "overextended"


class ScenarioSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLabel(str, Enum):
    SAFE = "Safe"
    MODERATE = "Moderate Risk"
    HIGH = "High Risk"


class BiasType(str, Enum):
    FOMO = "FOMO"
    OVERCONFIDENCE = "overconfidence"
    ANCHORING = "anchoring"
    SOCIAL_PRESSURE = "social_pressure"
    SCARCITY_BIAS = "scarcity_bias"
    OPTIMISM_BIAS = "optimism_bias"
    DENIAL = "denial"


class BiasSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verdict(str, Enum):
    BUY_SAFE = "buy_safe"
    BUY_CAUTION = "buy_caution"
    WAIT = "wait"
    TOO_RISKY = "too_risky"


class MessageType(str, Enum):
    OBSERVATION = "observation"
    CHALLENGE = "challenge"
    QUESTION = "question"
    AGREEMENT = "agreement"
    REVISION = "revision"
    CONCLUSION = "conclusion"


class ConversationIntent(str, Enum):
    NEW_ANALYSIS = "new_analysis"
    UPDATE_INPUT = "update_input"
    ASK_QUESTION = "ask_question"
    COMPARE = "compare"
    EXPORT = "export"


class SessionStatus(str, Enum):
    STARTED = "started"
    BEHAVIORAL_DONE = "behavioral_done"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    ERROR = "error"


class PropertyType(str, Enum):
    UNDER_CONSTRUCTION = "under_construction"
    READY_TO_MOVE = "ready_to_move"


# Input models

class UserInput(BaseModel):
    # Monthly income after tax in rupees
    monthly_income: float
    # Fixed monthly expenses excluding EMI in rupees
    monthly_expenses: float
    # Total savings available right now in rupees
    total_savings: float
    # Amount available for down payment in rupees
    down_payment: float
    # Property price being considered in rupees
    property_price: float
    # Loan tenure in years
    tenure_years: int
    # Expected annual interest rate as decimal eg 0.085 for 8.5%
    annual_interest_rate: float
    # Age of the primary applicant
    age: int
    # State in India for stamp duty calculation
    state: str
    # Under construction or ready to move
    property_type: PropertyType
    # Area in square feet for maintenance calculation
    area_sqft: Optional[float] = None
    # Session this input belongs to
    session_id: str


class BehavioralAnswer(BaseModel):
    # Question number 1 through 7
    question_id: int
    # The question text
    question: str
    # User's answer
    answer: str
    # Bias signal this question is designed to detect
    bias_signal: str


class BehavioralIntake(BaseModel):
    session_id: str
    answers: List[BehavioralAnswer]


class ConversationMessage(BaseModel):
    session_id: str
    # Raw natural language message from user
    message: str


# India defaults output

class IndiaCostBreakdown(BaseModel):
    base_price: float
    stamp_duty: float
    stamp_duty_rate: float
    registration_fee: float
    gst: float
    gst_applicable: bool
    maintenance_deposit: float
    loan_processing_fee: float
    legal_charges: float
    true_total_cost: float
    # Annual tax benefit under 80C on principal
    tax_benefit_80c: float
    # Annual tax benefit under 24B on interest
    tax_benefit_24b: float


# Deterministic agent outputs

class FinancialRealityOutput(BaseModel):
    emi: float
    emi_to_income_ratio: float
    monthly_surplus_after_emi: float
    # Cash flow for each of the next 12 months as array
    cash_flow_12_months: List[float]
    # Month number when savings hit zero, null if never
    savings_depletion_month: Optional[int]
    # Property price where EMI is exactly 35% of income
    safe_property_price: float
    # Property price where EMI is exactly 50% of income
    maximum_property_price: float
    affordability_status: AffordabilityStatus
    india_cost_breakdown: IndiaCostBreakdown
    loan_amount: float
    total_interest_payable: float


class ScenarioOutput(BaseModel):
    scenario_name: str
    survivable: bool
    buffer_months: int
    # Monthly shortfall when income is reduced
    monthly_shortfall: Optional[float]
    # Month at which savings are fully depleted
    breaking_point_month: Optional[int]
    severity: ScenarioSeverity
    # One sentence plain description of this scenario outcome
    description: str
    modified_emi: Optional[float]
    modified_monthly_income: Optional[float]


class AllScenariosOutput(BaseModel):
    base_case: ScenarioOutput
    income_drop_30pct: ScenarioOutput
    job_loss_6_months: ScenarioOutput
    interest_rate_hike_2pct: ScenarioOutput
    emergency_expense_5L: ScenarioOutput
    # How many of the 5 scenarios are survivable
    scenarios_survived: int


class RiskScoreComponentScores(BaseModel):
    # EMI to income ratio component out of 35
    emi_ratio_score: float
    # Savings buffer component out of 25
    buffer_score: float
    # Scenario survival component out of 30
    scenario_survival_score: float
    # Tenure vs earning years component out of 10
    tenure_age_score: float


class RiskScoreOutput(BaseModel):
    composite_score: float
    component_scores: RiskScoreComponentScores
    risk_label: RiskLabel
    # List of factors that are driving the risk score up
    risk_factors: List[str]
    # Plain English explanation of each component
    score_explanation: Dict[str, str]


# AI agent outputs

class BiasFlagItem(BaseModel):
    bias_type: BiasType
    severity: BiasSeverity
    # What specific input triggered this flag
    evidence: str
    # What financial risk does this bias create
    implication: str


class BehavioralAnalysisOutput(BaseModel):
    bias_flags: List[BiasFlagItem]
    # Overall behavioral risk score from 0 to 10
    behavioral_risk_score: float
    # Questions to ask user to surface deeper bias
    recommended_questions: List[str]
    # Plain English behavioral profile summary
    summary: str
    # True if user has shown signs of emotional commitment to a specific property
    emotionally_committed: bool


class VerdictOutput(BaseModel):
    verdict: Verdict
    # Confidence in this verdict from 0 to 100
    confidence: float
    primary_reasons: List[str]
    key_warnings: List[str]
    safe_price_recommendation: float
    suggested_actions: List[str]
    # Conflicts from validation agent that could not be resolved
    unresolved_conflicts: List[str]
    # 2 to 3 paragraph narrative written directly to the user
    final_narrative: str


class ChartDataset(BaseModel):
    label: str
    data: List[float]
    # CSS color string for this dataset
    color: str


class CashFlowChartData(BaseModel):
    # Month labels eg Month 1 Month 2
    labels: List[str]
    datasets: List[ChartDataset]


class ScenarioComparisonData(BaseModel):
    scenario_names: List[str]
    buffer_months: List[int]
    survivable: List[bool]
    severity_colors: List[str]


class AffordabilityBarData(BaseModel):
    asked_price: float
    safe_price: float
    maximum_price: float


class RiskGaugeData(BaseModel):
    score: float
    label: RiskLabel
    # CSS color for gauge fill
    color: str


class WarningCard(BaseModel):
    title: str
    description: str
    # low medium or high
    severity: str
    # financial behavioral or assumption
    category: str


class PDFSection(BaseModel):
    title: str
    content: str


class PDFContent(BaseModel):
    session_id: str
    user_name: str
    generated_at: str
    risk_score_section: PDFSection
    scenario_section: PDFSection
    cash_flow_section: PDFSection
    behavioral_section: PDFSection
    action_items_section: PDFSection


class PresentationOutput(BaseModel):
    formatted_risk_summary: str
    scenario_explanations: Dict[str, str]
    behavioral_summary: str
    cash_flow_chart_data: CashFlowChartData
    scenario_comparison_data: ScenarioComparisonData
    affordability_bar_data: AffordabilityBarData
    risk_gauge_data: RiskGaugeData
    warning_cards: List[WarningCard]
    verdict_display: Dict[str, Any]
    pdf_content: PDFContent


# Validation agent outputs

class AssumptionItem(BaseModel):
    assumption: str
    # Which agent made this assumption
    source_agent: str
    # Is this assumption risky
    flagged: bool
    flag_reason: Optional[str]


class ConflictItem(BaseModel):
    description: str
    agents_involved: List[str]
    severity: str
    resolution_suggestion: str


class ValidationOutput(BaseModel):
    assumptions_log: List[AssumptionItem]
    flagged_assumptions: List[AssumptionItem]
    conflicts: List[ConflictItem]
    # How reliable are the inputs from 0 to 100
    data_quality_score: float


# Context and conversation outputs

class ContextState(BaseModel):
    session_id: str
    # Summary injected into every agent call
    context_summary: str
    # What changed since the last turn
    changed_inputs: Dict[str, Any]
    # Last 5 turns of conversation
    relevant_history: List[Dict[str, str]]
    # How assumptions evolved across turns
    assumption_evolution: List[str]
    turn_number: int


class ConversationOutput(BaseModel):
    # Parsed structured input from natural language
    structured_input: Dict[str, Any]
    intent: ConversationIntent
    # Financial variables that changed
    extracted_variables: Dict[str, Any]
    # Follow up question if user input was ambiguous
    follow_up_question: Optional[str]
    # Which agents need to rerun based on what changed
    trigger_agents: List[str]
    # Immediate acknowledgment to show the user
    response_to_user: str


# Roundtable models

class AgentMessage(BaseModel):
    agent: str
    message_type: MessageType
    content: str
    round: int
    timestamp: str
    # Agent this message is directed at, null means all
    directed_at: Optional[str] = None


class RoundSummary(BaseModel):
    round_number: int
    messages: List[AgentMessage]
    # Did this round produce new information
    productive: bool
    # Open questions remaining after this round
    open_questions: List[str]
    # Conflicts identified in this round
    conflicts_identified: List[str]


class BlackboardState(BaseModel):
    session_id: str
    user_input: Optional[UserInput] = None
    behavioral_intake: Optional[BehavioralIntake] = None
    india_cost_breakdown: Optional[IndiaCostBreakdown] = None
    financial_reality: Optional[FinancialRealityOutput] = None
    all_scenarios: Optional[AllScenariosOutput] = None
    risk_score: Optional[RiskScoreOutput] = None
    behavioral_analysis: Optional[BehavioralAnalysisOutput] = None
    validation: Optional[ValidationOutput] = None
    presentation: Optional[PresentationOutput] = None
    verdict: Optional[VerdictOutput] = None
    discussion_transcript: List[AgentMessage] = []
    round_summaries: List[RoundSummary] = []
    current_round: int = 0
    # Flags raised by any agent during discussion
    active_flags: List[str] = []
    # Questions not yet resolved in the discussion
    open_questions: List[str] = []
    converged: bool = False


# Session models

class SessionState(BaseModel):
    session_id: str
    user_id: str
    title: str
    city: Optional[str] = None
    state: Optional[str] = None
    status: SessionStatus
    created_at: str
    updated_at: str


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    risk_label: Optional[RiskLabel] = None
    verdict: Optional[Verdict] = None
    # One line summary of the verdict
    verdict_summary: Optional[str] = None
    property_price: Optional[float] = None
    city: Optional[str] = None


# Report models

class ReportOutput(BaseModel):
    session_id: str
    # Signed GCS URL for downloading the PDF
    gcs_url: str
    generated_at: str


# API response wrappers

class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


class AnalysisResponse(BaseModel):
    session_id: str
    financial_reality: FinancialRealityOutput
    all_scenarios: AllScenariosOutput
    risk_score: RiskScoreOutput
    behavioral_analysis: BehavioralAnalysisOutput
    validation: ValidationOutput
    presentation: PresentationOutput
    verdict: VerdictOutput


class SessionStartResponse(BaseModel):
    session_id: str
    user_id: str
    created_at: str


class ConversationResponse(BaseModel):
    session_id: str
    conversation_output: ConversationOutput
    updated_analysis: Optional[AnalysisResponse] = None