# backend/services/policy_tools.py — Production Canonical Employee DB & 3 Non-Overlapping Policy Tools
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from backend.schemas.policy import (
    EmployeeRecord,
    JurisdictionEnum,
    PolicyCategoryEnum,
)

# ---------------------------------------------------------------------------
# Canonical Verified Employee Database (10 Benchmark Profiles)
# ---------------------------------------------------------------------------

CANONICAL_EMPLOYEES: Dict[str, EmployeeRecord] = {
    "EMP001": EmployeeRecord(
        employee_id="EMP001",
        name="Sarah Mwangi",
        job_title="Senior Program Officer",
        department="Operations",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=18,
        employment_status="Confirmed",
        annual_leave_balance=12,
        basic_salary_monthly=3500.0,
        separation_reason=None,
    ),
    "EMP002": EmployeeRecord(
        employee_id="EMP002",
        name="Brian O'Connor",
        job_title="Finance Specialist",
        department="Finance",
        duty_station="Dublin",
        jurisdiction=JurisdictionEnum.IRELAND,
        tenure_months=24,
        employment_status="Confirmed",
        annual_leave_balance=18,
        basic_salary_monthly=4200.0,
        separation_reason=None,
    ),
    "EMP003": EmployeeRecord(
        employee_id="EMP003",
        name="David Omondi",
        job_title="Junior Field Assistant",
        department="Field Services",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=4,
        employment_status="Probation",
        annual_leave_balance=4,
        basic_salary_monthly=1800.0,
        separation_reason=None,
    ),
    "EMP004": EmployeeRecord(
        employee_id="EMP004",
        name="Grace Wanjiru",
        job_title="Regional Director",
        department="Executive",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=36,
        employment_status="Confirmed",
        annual_leave_balance=20,
        basic_salary_monthly=6000.0,
        separation_reason=None,
    ),
    "EMP005": EmployeeRecord(
        employee_id="EMP005",
        name="Kevin Ndirangu",
        job_title="Logistics Coordinator",
        department="Logistics",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=1,
        employment_status="Probation",
        annual_leave_balance=2,
        basic_salary_monthly=2200.0,
        separation_reason=None,
    ),
    "EMP006": EmployeeRecord(
        employee_id="EMP006",
        name="Amina Kone",
        job_title="Human Resources Officer",
        department="People & Culture",
        duty_station="Abidjan",
        jurisdiction=JurisdictionEnum.COTE_D_IVOIRE,
        tenure_months=14,
        employment_status="Confirmed",
        annual_leave_balance=10,
        basic_salary_monthly=2800.0,
        separation_reason=None,
    ),
    "EMP007": EmployeeRecord(
        employee_id="EMP007",
        name="Peter Mugisha",
        job_title="Country Representative",
        department="Country Operations",
        duty_station="Kigali",
        jurisdiction=JurisdictionEnum.RWANDA,
        tenure_months=48,
        employment_status="Confirmed",
        annual_leave_balance=15,
        basic_salary_monthly=5000.0,
        separation_reason="Redundancy",
    ),
    "EMP008": EmployeeRecord(
        employee_id="EMP008",
        name="Faith Chebet",
        job_title="Associate Researcher",
        department="Policy & Research",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=12,
        employment_status="Confirmed",
        annual_leave_balance=6,
        basic_salary_monthly=2500.0,
        separation_reason="Unsatisfactory Performance",
    ),
    "EMP009": EmployeeRecord(
        employee_id="EMP009",
        name="Emmanuel Gasana",
        job_title="IT Support Engineer",
        department="Information Technology",
        duty_station="Kigali",
        jurisdiction=JurisdictionEnum.RWANDA,
        tenure_months=4,
        employment_status="Probation",
        annual_leave_balance=3,
        basic_salary_monthly=2000.0,
        separation_reason=None,
    ),
    "EMP010": EmployeeRecord(
        employee_id="EMP010",
        name="Linda Akinyi",
        job_title="Senior Legal Counsel",
        department="Legal & Compliance",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=30,
        employment_status="Confirmed",
        annual_leave_balance=15,
        basic_salary_monthly=5500.0,
        separation_reason="Resignation",
    ),
}

# ---------------------------------------------------------------------------
# Handbook Policy Knowledge Base (Verbatim Clauses from HRPolicy.pdf)
# ---------------------------------------------------------------------------

HANDBOOK_CLAUSES: List[Dict[str, Any]] = [
    {
        "section": "Section 5.2.1",
        "title": "Annual Leave Entitlement & Accrual",
        "keywords": ["annual leave", "entitlement", "accrual", "24 working days", "2 days", "working days"],
        "content": (
            "5.2.1 Full-time staff members are entitled to annual leave of 24 working days per annum, "
            "which shall accrue at the rate of 2 working days per month of completed service."
        ),
    },
    {
        "section": "Section 5.2.7",
        "title": "Annual Leave Carry Forward & Year-End Cap",
        "keywords": ["carry forward", "carryover", "unused leave", "5 days", "december 31", "june 30"],
        "content": (
            "5.2.7 A staff member may not carry forward more than five (5) days of accrued unused annual leave "
            "from one calendar year into the next without the prior written approval of the Chief Executive Officer (CEO). "
            "Any carried forward leave must be taken before June 30th of the following year, otherwise it is forfeited."
        ),
    },
    {
        "section": "Section 10.1 & Section 3.6.4",
        "title": "Resignation Notice Requirements (Probation vs Confirmed)",
        "keywords": ["resignation", "notice", "probation", "1 week", "7 days", "written notice", "resign"],
        "content": (
            "10.1 Notice of Resignation: Staff members on probation may terminate their employment by giving "
            "one (1) week (7 calendar days) written notice. Confirmed staff members are required to give four (4) "
            "weeks written notice of resignation to the organization."
        ),
    },
    {
        "section": "Section 5.3.2",
        "title": "Paid Sick Leave Eligibility & Accrual",
        "keywords": ["sick leave", "paid sick leave", "2 consecutive months", "two consecutive months", "2 working days", "full pay", "half pay", "7 days"],
        "content": (
            "5.3.2 A staff member who has completed at least two (2) consecutive months of service and is incapacitated "
            "by illness or injury is entitled to paid sick leave. Paid sick leave accrues at the rate of two (2) working days "
            "per month of completed service, with one (1) day at full pay and one (1) day at half pay, subject to a minimum "
            "of 7 days at full pay and 7 days at half pay (maximum entitlement of three months full pay and three months half pay)."
        ),
    },
    {
        "section": "Section 10.5.1",
        "title": "Redundancy Notice & Severance Entitlement",
        "keywords": ["redundancy", "severance", "15 days", "completed years", "notice period", "1 month"],
        "content": (
            "10.5.1 In the event of separation due to redundancy, the employee shall receive one (1) month written notice "
            "(or payment in lieu of notice) plus severance pay calculated as fifteen (15) days' basic pay for each completed year of service."
        ),
    },
    {
        "section": "Section 10.5.2",
        "title": "Termination for Unsatisfactory Performance",
        "keywords": ["unsatisfactory performance", "performance", "severance", "0 severance", "not entitled"],
        "content": (
            "10.5.2 Staff members separated from service due to unsatisfactory performance are not entitled to severance payments. "
            "The employee shall receive only accrued unused annual leave and payment for days worked up to the date of separation."
        ),
    },
    {
        "section": "Section 4.4.1",
        "title": "Pension Contribution & Post-Probation Eligibility",
        "keywords": ["pension", "probation", "allowance", "10%", "contribution", "eligibility"],
        "content": (
            "4.4.1 Staff members on probation are not eligible for the 10% pension contribution allowance. Upon successful "
            "completion and confirmation of probation, the organization shall provide a pension contribution allowance equal to "
            "10% of the employee's basic monthly salary."
        ),
    },
    {
        "section": "Section 10.7",
        "title": "Commutation of Accrued Annual Leave upon Separation",
        "keywords": ["commutation", "cash", "separation", "10 working days", "accrued leave", "gross salary"],
        "content": (
            "10.7 Upon separation from service, a staff member may commute accrued unused annual leave to cash up to a maximum "
            "of ten (10) working days, calculated based on gross salary."
        ),
    },
]

# ---------------------------------------------------------------------------
# Duty Station Statutory Guidelines (Jurisdiction Rules Knowledge Base)
# ---------------------------------------------------------------------------

JURISDICTION_RULES: Dict[str, Dict[str, str]] = {
    "Kenya": {
        "leave": "Statutory minimum annual leave in Kenya is 21 working days. Organizational policy provides 24 working days (superior benefit).",
        "notice_and_separation": "Employment Act 2007 requires minimum 28 days notice for confirmed staff; probation notice is 7 days.",
        "benefits_and_pension": "Mandatory NSSF Tier I & Tier II contributions apply; voluntary organizational pension is 10% post-probation.",
        "holidays_and_working_hours": "11 statutory gazetted public holidays; standard workweek is 40 hours.",
        "conduct_and_discipline": "Fair hearing mandated under Section 41 prior to disciplinary termination.",
    },
    "Ireland": {
        "leave": "Organisation of Working Time Act 1997 provides 4 working weeks (20 days). Organizational policy provides 24 working days.",
        "notice_and_separation": "Minimum Notice and Terms of Employment Acts 1973-2005 apply based on continuous service length.",
        "benefits_and_pension": "PRSA pension contribution access mandated under Irish employment law.",
        "holidays_and_working_hours": "10 statutory public holidays per annum; maximum 48-hour average workweek.",
        "conduct_and_discipline": "Workplace Relations Commission (WRC) statutory disciplinary guidelines apply.",
    },
    "Cote d'Ivoire": {
        "leave": "Labour Code Article 25 provides 2.2 working days per month of service (26.4 days/year).",
        "notice_and_separation": "Notice periods determined by collective bargaining agreement and occupational category.",
        "benefits_and_pension": "CNPS statutory pension contributions apply to both employer and employee.",
        "holidays_and_working_hours": "Statutory 40-hour workweek for non-agricultural sectors.",
        "conduct_and_discipline": "Strict written notification procedure required for disciplinary dismissal.",
    },
    "Rwanda": {
        "leave": "Law No 66/2018 regulating labor in Rwanda guarantees 18 working days minimum annual leave.",
        "notice_and_separation": "15 days notice for tenure under 1 year; 30 days notice for tenure exceeding 1 year.",
        "benefits_and_pension": "RSSB (Rwanda Social Security Board) statutory pension scheme participation mandatory.",
        "holidays_and_working_hours": "Standard 45-hour workweek as per Rwandan labor legislation.",
        "conduct_and_discipline": "Labor inspectorate notification required for collective redundancies.",
    },
    "Global": {
        "leave": "Global standard annual leave entitlement is 24 working days per annum, accruing at 2 days per month.",
        "notice_and_separation": "Standard probation notice is 1 week (7 days); confirmed staff notice is 4 weeks.",
        "benefits_and_pension": "10% pension contribution allowance provided to confirmed staff only.",
        "holidays_and_working_hours": "Standard organizational core working hours apply across all duty stations.",
        "conduct_and_discipline": "Organizational Code of Conduct and Disciplinary Policy governs all staff globally.",
    },
}

# ---------------------------------------------------------------------------
# Tool 1: get_employee_record
# ---------------------------------------------------------------------------

def get_employee_record(employee_id: str) -> Dict[str, Any]:
    """
    Retrieve employee profile details (tenure, employment status, salary, department, jurisdiction).
    """
    emp_id = (employee_id or "").strip().upper()
    record = CANONICAL_EMPLOYEES.get(emp_id)
    if not record:
        return {"found": False, "error": f"Employee record '{employee_id}' not found in canonical database."}
    return {
        "found": True,
        "employee_id": record.employee_id,
        "name": record.name,
        "job_title": record.job_title,
        "department": record.department,
        "duty_station": record.duty_station,
        "jurisdiction": record.jurisdiction.value,
        "tenure_months": record.tenure_months,
        "employment_status": record.employment_status,
        "annual_leave_balance": record.annual_leave_balance,
        "basic_salary_monthly": record.basic_salary_monthly,
        "separation_reason": record.separation_reason,
    }

# ---------------------------------------------------------------------------
# Tool 2: search_handbook
# ---------------------------------------------------------------------------

def search_handbook(query: str, top_k: int = 2) -> List[Dict[str, Any]]:
    """
    Search the organizational Human Resources Policy Manual (HRPolicy.pdf) for relevant policy clauses.
    """
    q_words = [w.lower() for w in query.replace(",", " ").replace("?", " ").split() if len(w) > 2]
    scored_clauses = []
    for clause in HANDBOOK_CLAUSES:
        score = 0
        text = (clause["section"] + " " + clause["title"] + " " + clause["content"] + " " + " ".join(clause["keywords"])).lower()
        for kw in clause["keywords"]:
            if kw.lower() in query.lower():
                score += 5
        for w in q_words:
            if w in text:
                score += 1
        if score > 0:
            scored_clauses.append((score, clause))

    scored_clauses.sort(key=lambda x: x[0], reverse=True)
    top_results = [c[1] for c in scored_clauses[:top_k]]
    if not top_results:
        top_results = [HANDBOOK_CLAUSES[0]]
    return top_results

# ---------------------------------------------------------------------------
# Tool 3: get_jurisdiction_rules
# ---------------------------------------------------------------------------

def get_jurisdiction_rules(jurisdiction: JurisdictionEnum, policy_category: PolicyCategoryEnum) -> Dict[str, Any]:
    """
    Retrieve statutory duty-station guidelines and public holiday frameworks for a specific jurisdiction.
    """
    jur_key = jurisdiction.value if isinstance(jurisdiction, JurisdictionEnum) else str(jurisdiction)
    cat_key = policy_category.value if isinstance(policy_category, PolicyCategoryEnum) else str(policy_category)

    jur_dict = JURISDICTION_RULES.get(jur_key, JURISDICTION_RULES["Global"])
    guideline = jur_dict.get(cat_key, f"Standard organizational policy applies for {jur_key} under {cat_key}.")

    return {
        "jurisdiction": jur_key,
        "policy_category": cat_key,
        "statutory_guideline": guideline,
    }

# ---------------------------------------------------------------------------
# Tool Registry & JSON Schema Definitions (For ReAct Agent)
# ---------------------------------------------------------------------------

POLICY_TOOL_DEFINITIONS = [
    {
        "name": "get_employee_record",
        "description": "Retrieve employee profile details including employment status (Probation vs Confirmed), tenure in months, jurisdiction duty station, salary, and leave balance.",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string", "description": "The unique employee ID, e.g. EMP001"}
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "search_handbook",
        "description": "Search the organizational HR policy manual text for policy sections, entitlements, notice rules, and severance calculations.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The policy search query, e.g. 'annual leave entitlement'"},
                "top_k": {"type": "integer", "description": "Number of top matching sections to return (default 2)"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_jurisdiction_rules",
        "description": "Retrieve jurisdiction-specific statutory rules, public holiday entitlements, local statutory compliance baselines, and duty-station guidelines.",
        "parameters": {
            "type": "object",
            "properties": {
                "jurisdiction": {
                    "type": "string",
                    "enum": ["Kenya", "Ireland", "Cote d'Ivoire", "Rwanda", "Global"],
                    "description": "The duty station jurisdiction.",
                },
                "policy_category": {
                    "type": "string",
                    "enum": ["leave", "notice_and_separation", "benefits_and_pension", "holidays_and_working_hours", "conduct_and_discipline"],
                    "description": "The specific policy category to retrieve.",
                },
            },
            "required": ["jurisdiction", "policy_category"],
        },
    },
]

def execute_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Dispatches tool execution by name."""
    if tool_name == "get_employee_record":
        return get_employee_record(arguments.get("employee_id", ""))
    elif tool_name == "search_handbook":
        return search_handbook(arguments.get("query", ""), top_k=arguments.get("top_k", 2))
    elif tool_name == "get_jurisdiction_rules":
        jur = arguments.get("jurisdiction", "Global")
        cat = arguments.get("policy_category", "leave")
        return get_jurisdiction_rules(JurisdictionEnum(jur), PolicyCategoryEnum(cat))
    else:
        return {"error": f"Unknown tool: '{tool_name}'"}
