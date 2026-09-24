# backend/services/week7_tools.py — Canonical Tools for Week 7 Agent & Fixed Workflow
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from backend.schemas.week7 import (
    EmployeeRecord,
    JurisdictionEnum,
    PolicyCategoryEnum,
)

# ---------------------------------------------------------------------------
# Canonical Employee Database (10 Benchmark Employees)
# ---------------------------------------------------------------------------

CANONICAL_EMPLOYEES: Dict[str, EmployeeRecord] = {
    "EMP001": EmployeeRecord(
        employee_id="EMP001",
        name="Sarah Mwangi",
        job_title="Programme Manager",
        department="Education & Development",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=18,
        employment_status="Confirmed",
        annual_leave_balance=14,
        basic_salary_monthly=4500.0,
        separation_reason=None,
    ),
    "EMP002": EmployeeRecord(
        employee_id="EMP002",
        name="David Ochieng",
        job_title="Senior Technology Specialist",
        department="Information Technology",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=36,
        employment_status="Confirmed",
        annual_leave_balance=8,
        basic_salary_monthly=5200.0,
        separation_reason=None,
    ),
    "EMP003": EmployeeRecord(
        employee_id="EMP003",
        name="Amina Yusuf",
        job_title="Project Officer",
        department="Policy & Strategy",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=4,
        employment_status="Probation",
        annual_leave_balance=4,
        basic_salary_monthly=3200.0,
        separation_reason=None,
    ),
    "EMP004": EmployeeRecord(
        employee_id="EMP004",
        name="Brian Kiprono",
        job_title="Finance Specialist",
        department="Finance & Operations",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=36,
        employment_status="Confirmed",
        annual_leave_balance=12,
        basic_salary_monthly=4800.0,
        separation_reason=None,
    ),
    "EMP005": EmployeeRecord(
        employee_id="EMP005",
        name="Kevin O'Connor",
        job_title="Junior Policy Advisor",
        department="Global Strategy",
        duty_station="Dublin",
        jurisdiction=JurisdictionEnum.IRELAND,
        tenure_months=1,
        employment_status="Probation",
        annual_leave_balance=2,
        basic_salary_monthly=3800.0,
        separation_reason=None,
    ),
    "EMP006": EmployeeRecord(
        employee_id="EMP006",
        name="Grace Wanjiku",
        job_title="Monitoring & Evaluation Specialist",
        department="Operations",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=14,
        employment_status="Confirmed",
        annual_leave_balance=10,
        basic_salary_monthly=4100.0,
        separation_reason=None,
    ),
    "EMP007": EmployeeRecord(
        employee_id="EMP007",
        name="Michael Njoroge",
        job_title="Field Operations Coordinator",
        department="Programmes",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=48,
        employment_status="Confirmed",
        annual_leave_balance=15,
        basic_salary_monthly=3900.0,
        separation_reason="Redundancy",
    ),
    "EMP008": EmployeeRecord(
        employee_id="EMP008",
        name="Daniel Mutua",
        job_title="Research Assistant",
        department="Policy Research",
        duty_station="Nairobi",
        jurisdiction=JurisdictionEnum.KENYA,
        tenure_months=36,
        employment_status="Confirmed",
        annual_leave_balance=5,
        basic_salary_monthly=3000.0,
        separation_reason="Unsatisfactory Performance",
    ),
    "EMP009": EmployeeRecord(
        employee_id="EMP009",
        name="Fatou Diallo",
        job_title="Regional HR Officer",
        department="Human Resources",
        duty_station="Abidjan",
        jurisdiction=JurisdictionEnum.COTE_D_IVOIRE,
        tenure_months=4,
        employment_status="Probation",
        annual_leave_balance=6,
        basic_salary_monthly=3400.0,
        separation_reason=None,
    ),
    "EMP010": EmployeeRecord(
        employee_id="EMP010",
        name="Patrick Ndung'u",
        job_title="Senior Advisor",
        department="Strategic Partnerships",
        duty_station="Kigali",
        jurisdiction=JurisdictionEnum.RWANDA,
        tenure_months=60,
        employment_status="Confirmed",
        annual_leave_balance=15,
        basic_salary_monthly=5500.0,
        separation_reason="Separation from service",
    ),
}


# ---------------------------------------------------------------------------
# Curated Verified Handbook Knowledge Index (Extracted directly from HRPolicy.pdf)
# ---------------------------------------------------------------------------

HANDBOOK_KNOWLEDGE_BASE: List[Dict[str, Any]] = [
    {
        "section": "Section 5.2.1",
        "title": "Annual Leave Entitlement",
        "page": 32,
        "keywords": ["annual leave", "entitlement", "rate", "accrual", "vacation", "days per annum", "24 days", "2 days per month"],
        "text": (
            "Section 5.2.1 Annual leave entitlement:\n"
            "Annual leave entitlement for each staff member is set out in their contract of employment. "
            "The standard entitlement for full-time staff members is 24 days per annum. Calculations of "
            "annual leave for service of less than one year shall be made in proportion to the length of "
            "service. This means that leave accrues at the rate of 2 days per month. GESCI's annual leave "
            "year runs from 1st January to 31st December."
        ),
    },
    {
        "section": "Section 5.2.7",
        "title": "Carry Forward of Leave",
        "page": 34,
        "keywords": ["carry forward", "carryover", "annual leave", "december 31", "june 30", "5 days", "consent of ceo"],
        "text": (
            "Section 5.2.7 Carry forward of leave:\n"
            "Staff members shall not, except with the consent of the CEO, carry forward more than 5 days "
            "out of their annual leave entitlement beyond December 31st. Any approved days carried forward "
            "must be taken by 30th June the following year."
        ),
    },
    {
        "section": "Section 10.1 & Section 3.6.4",
        "title": "Resignation & Notice Period (Probation vs Confirmed)",
        "page": 69,
        "keywords": ["resignation", "notice", "notice period", "probation", "confirmed", "written notice", "1 week", "4 weeks", "7 days"],
        "text": (
            "Section 10.1 Resignation & Section 3.6.4 Non-Confirmation / Probation:\n"
            "A resignation is a separation from GESCI initiated by the staff member. A staff member resigning "
            "must give GESCI four weeks written notice, or one week written notice (7 days) in the case of staff "
            "members on probation. The CEO may accept resignation on shorter notice."
        ),
    },
    {
        "section": "Section 5.3.2",
        "title": "Sick Leave Eligibility, Accrual & Entitlement",
        "page": 35,
        "keywords": ["sick leave", "illness", "injury", "accrual", "2 consecutive months", "2 working days", "full pay", "half pay", "minimum 7 days", "maximum 3 months"],
        "text": (
            "Section 5.3.2 Sick Leave:\n"
            "A staff member's entitlement to paid sick leave shall be determined by the duration of the staff "
            "member's service with GESCI subject to a minimum and maximum and provided the staff member has "
            "completed at least two consecutive months of service. A staff member who has not completed two "
            "consecutive months is not yet eligible for paid sick leave.\n"
            "A staff member is entitled to sick leave at the rate of two working days per month of completed service "
            "of which one day is at full pay and one day is at half pay subject to: (a) Minimum of 7 days at full pay "
            "and 7 days at half pay; and (b) Maximum of three months on full pay and three months on half pay "
            "regardless of length of service. Uncertified sick leave is permitted up to 7 working days per annual "
            "cycle (max 3 consecutive days without medical certificate)."
        ),
    },
    {
        "section": "Section 10.5.1",
        "title": "Termination for Redundancy & Severance Pay",
        "page": 70,
        "keywords": ["redundancy", "severance", "severance pay", "notice", "1 month notice", "15 days", "completed year of service", "calculation"],
        "text": (
            "Section 10.5.1 Termination for redundancy:\n"
            "A staff member whose employment has been declared redundant will receive one month's written notice "
            "giving reasons for the redundancy (or payment equal to one month salary in lieu of notice).\n"
            "Severance payments: Staff members whose appointments are terminated on grounds of redundancy will be "
            "entitled to payments equal to all outstanding salary, pro rata salary for any accrued but not taken leave "
            "days, and severance pay at the rate of fifteen days' pay for each completed year of service."
        ),
    },
    {
        "section": "Section 10.5.2",
        "title": "Termination for Unsatisfactory Performance",
        "page": 71,
        "keywords": ["unsatisfactory performance", "performance", "severance", "notice", "not entitled to severance", "0 severance"],
        "text": (
            "Section 10.5.2 Termination for unsatisfactory performance or service:\n"
            "A staff member whose employment is being terminated for unsatisfactory performance will receive one month's "
            "written notice (or one month salary in lieu).\n"
            "Severance pay: A staff member separated for reasons of unsatisfactory performance is NOT entitled to severance "
            "payments (0 severance pay). However, the staff member will receive payments for any accrued unused leave and "
            "accrued pay for time already worked."
        ),
    },
    {
        "section": "Section 4.4.1",
        "title": "Pension Contribution Allowance",
        "page": 27,
        "keywords": ["pension", "pension allowance", "probation", "10%", "basic salary", "eligibility", "contribution"],
        "text": (
            "Section 4.4.1 Pension Contribution Allowance:\n"
            "In lieu of a Pension Scheme, GESCI provides a pension contribution allowance equal to 10% of the staff "
            "member's basic salary once the probation period is successfully completed. Staff members currently on probation "
            "are not eligible to receive the pension contribution allowance until probation is confirmed."
        ),
    },
    {
        "section": "Section 10.7",
        "title": "Commutation of Accrued Annual Leave Upon Separation",
        "page": 73,
        "keywords": ["commutation", "separation", "accrued leave", "cash", "10 working days", "gross salary", "leaving organization"],
        "text": (
            "Section 10.7 Commutation of accrued annual leave:\n"
            "If, upon separation from service a staff member has accrued annual leave, he or she shall be paid a sum of "
            "money in commutation of the period of such accrued leave up to a maximum of 10 working days on the basis "
            "of gross salary alone."
        ),
    },
]


# ---------------------------------------------------------------------------
# Statutory & Duty Station Jurisdiction Rules Base
# ---------------------------------------------------------------------------

JURISDICTION_RULES_BASE: Dict[str, Dict[str, str]] = {
    "Kenya": {
        "leave": "Under Kenyan Employment Act & GESCI HRPPM, standard annual leave is 24 working days/year (2 days/month). Sick leave accrual is 2 days/month (1 full/1 half pay) after 2 months service.",
        "notice_and_separation": "In Kenya duty station, resignation notice is 1 week during probation (Section 3.6.4/10.1) and 4 weeks post-confirmation (Section 10.1). Redundancy severance is 15 days pay per completed year (Section 10.5.1). Performance dismissal has 0 severance (Section 10.5.2).",
        "benefits_and_pension": "Pension contribution allowance of 10% basic salary becomes active following completion of the 6-month probation period.",
        "holidays_and_working_hours": "Official working week is 40 hours (Monday-Friday 9:00am - 5:30pm). Staff observe official Kenya gazetted public holidays plus GESCI company holidays (Christmas/Easter).",
        "conduct_and_discipline": "Governed by Section 9 & 10. Misdemeanors result in warnings; gross misconduct results in immediate summary dismissal under Kenyan law.",
    },
    "Ireland": {
        "leave": "For Ireland-based assignments, staff adhere to GESCI global HRPPM annual leave (24 working days) and sick leave minimum qualification threshold (2 consecutive months).",
        "notice_and_separation": "Notice periods adhere to GESCI contract terms: 1 week during probation, 4 weeks post-confirmation.",
        "benefits_and_pension": "Expatriate/International reimbursement rules apply for medical and death/disability insurance under Section 4.4.2/4.4.3.",
        "holidays_and_working_hours": "Staff observe statutory Irish public holidays plus organization company holidays.",
        "conduct_and_discipline": "Standard GESCI code of conduct applies across all international operations.",
    },
    "Cote d'Ivoire": {
        "leave": "Standard 24 working days annual leave and global sick leave qualification thresholds apply.",
        "notice_and_separation": "Probation resignation notice is 1 week (7 days); confirmed notice is 4 weeks.",
        "benefits_and_pension": "Pension allowance of 10% of basic monthly salary applies post-probation confirmation.",
        "holidays_and_working_hours": "Staff observe local Cote d'Ivoire statutory holidays and standard 40-hour work week.",
        "conduct_and_discipline": "GESCI HRPPM disciplinary code of conduct applies.",
    },
    "Rwanda": {
        "leave": "Standard 24 working days annual leave and global sick leave rules apply.",
        "notice_and_separation": "Resignation notice is 1 week during probation and 4 weeks once confirmed. Separation leave commutation is capped at 10 working days.",
        "benefits_and_pension": "Pension contribution allowance of 10% payable following probation confirmation.",
        "holidays_and_working_hours": "Staff observe Rwanda public holidays and GESCI company holidays.",
        "conduct_and_discipline": "Standard GESCI code of conduct applies.",
    },
    "Global": {
        "leave": "Global HRPPM standard: 24 days/year annual leave (2 days/month), 5 days annual carryover cap, 16 weeks maternity, 2 weeks paternity, 5 days compassionate leave.",
        "notice_and_separation": "Standard notice: 1 week probation, 4 weeks confirmed. Separation commutation capped at 10 working days. Redundancy severance: 15 days/completed year.",
        "benefits_and_pension": "10% basic salary pension contribution allowance post-probation.",
        "holidays_and_working_hours": "Standard 40 hours/week.",
        "conduct_and_discipline": "HRPPM disciplinary policy Sections 9 and 10.",
    },
}


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

def get_employee_record(employee_id: str) -> Dict[str, Any]:
    """
    Retrieve the official HR employment record for a specific employee ID, including
    name, department, duty station, jurisdiction, tenure in months, employment status
    (Probation vs Confirmed), annual leave balance, monthly salary, and separation reason.
    """
    clean_id = employee_id.strip().upper()
    emp = CANONICAL_EMPLOYEES.get(clean_id)
    if not emp:
        return {
            "found": False,
            "error": f"Employee record with ID '{clean_id}' not found in canonical HR database.",
        }
    return {
        "found": True,
        "employee_id": emp.employee_id,
        "name": emp.name,
        "job_title": emp.job_title,
        "department": emp.department,
        "duty_station": emp.duty_station,
        "jurisdiction": emp.jurisdiction.value,
        "tenure_months": emp.tenure_months,
        "employment_status": emp.employment_status,
        "annual_leave_balance": emp.annual_leave_balance,
        "basic_salary_monthly": emp.basic_salary_monthly,
        "separation_reason": emp.separation_reason,
    }


def search_handbook(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Search the organization's Human Resource Policies and Procedure Manual (HRPPM)
    for general organizational rules, entitlements, leave calculations, notice periods,
    and separation provisions.
    """
    q_words = [w.lower() for w in query.split() if len(w) > 2]
    scored = []
    for doc in HANDBOOK_KNOWLEDGE_BASE:
        score = 0.0
        doc_text = (doc["title"] + " " + doc["section"] + " " + " ".join(doc["keywords"]) + " " + doc["text"]).lower()
        for w in q_words:
            if w in doc_text:
                score += 1.0
        if score > 0:
            scored.append((score, doc))
        else:
            scored.append((0.1, doc))

    scored.sort(key=lambda x: -x[0])
    return [
        {
            "section": doc["section"],
            "title": doc["title"],
            "page": doc["page"],
            "text": doc["text"],
            "score": round(score, 2),
        }
        for score, doc in scored[:top_k]
    ]


def get_jurisdiction_rules(
    jurisdiction: JurisdictionEnum,
    policy_category: PolicyCategoryEnum,
) -> Dict[str, Any]:
    """
    Retrieve jurisdiction-specific statutory rules, public holiday entitlements,
    local statutory compliance baselines, and duty-station statutory guidelines
    for a specified jurisdiction and policy category.
    """
    j_key = jurisdiction.value if isinstance(jurisdiction, JurisdictionEnum) else str(jurisdiction)
    c_key = policy_category.value if isinstance(policy_category, PolicyCategoryEnum) else str(policy_category)

    jur_data = JURISDICTION_RULES_BASE.get(j_key, JURISDICTION_RULES_BASE["Global"])
    category_rule = jur_data.get(c_key, jur_data.get("leave", "Standard organizational policy applies."))

    return {
        "jurisdiction": j_key,
        "policy_category": c_key,
        "statutory_guideline": category_rule,
        "governing_statute": f"Applicable statutory compliance framework for {j_key} duty station.",
    }


# ---------------------------------------------------------------------------
# Tool Declarations (Metadata for Agent & LLM Function Calling)
# ---------------------------------------------------------------------------

WEEK7_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "get_employee_record",
        "description": (
            "Retrieve the official HR employment record for a specific employee ID, including "
            "name, job title, department, duty station, jurisdiction, tenure in months, "
            "employment status (Probation vs Confirmed), annual leave balance, monthly salary, "
            "and separation reason. Use this tool when you need employee profile data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "The unique employee identifier (e.g. 'EMP001').",
                }
            },
            "required": ["employee_id"],
        },
    },
    {
        "name": "search_handbook",
        "description": (
            "Search the organization's Human Resource Policies and Procedure Manual (HRPPM) "
            "for general organizational rules, entitlements, leave calculations, notice periods, "
            "and separation provisions. Use this tool when querying policy clauses."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing the policy question or clause.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of top matching excerpts to return (default: 3).",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_jurisdiction_rules",
        "description": (
            "Retrieve jurisdiction-specific statutory rules, public holiday entitlements, "
            "local statutory compliance baselines, and duty-station guidelines for a specified "
            "jurisdiction and policy category. Use this tool for duty station statutory context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "jurisdiction": {
                    "type": "string",
                    "enum": [j.value for j in JurisdictionEnum],
                    "description": "The duty station jurisdiction.",
                },
                "policy_category": {
                    "type": "string",
                    "enum": [c.value for c in PolicyCategoryEnum],
                    "description": "The specific policy category to retrieve.",
                },
            },
            "required": ["jurisdiction", "policy_category"],
        },
    },
]


def execute_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Execute tool by name with arguments and return raw output."""
    if tool_name == "get_employee_record":
        emp_id = arguments.get("employee_id", "")
        return get_employee_record(emp_id)
    elif tool_name == "search_handbook":
        query = arguments.get("query", "")
        top_k = int(arguments.get("top_k", 3))
        return search_handbook(query, top_k=top_k)
    elif tool_name == "get_jurisdiction_rules":
        jur = arguments.get("jurisdiction", "Global")
        cat = arguments.get("policy_category", "leave")
        return get_jurisdiction_rules(jur, cat)
    else:
        raise ValueError(f"Unknown tool name: {tool_name}")
