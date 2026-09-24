# Tool Description & Architecture Diff: Jurisdiction Rules Tool

## 1. Summary of Changes
A dedicated tool `get_jurisdiction_rules` operates alongside `get_employee_record` and `search_handbook` to support duty-station statutory lookup without schema or semantic overlap.

## 2. Tool Separation & Non-Overlap Matrix

| Tool Name | Exact Responsibility | Parameter Types & Enums | Prevents Overlap With |
| :--- | :--- | :--- | :--- |
| **`get_employee_record`** | Retrieves individual employee profile attributes (tenure, status, salary, department, separation reason). | `employee_id: str` | `search_handbook` (does not search policy text); `get_jurisdiction_rules` (does not return employee records). |
| **`search_handbook`** | Performs keyword / semantic search against the global organization HRPPM policy manual text. | `query: str`, `top_k: int` | `get_employee_record` (does not look up employee profiles); `get_jurisdiction_rules` (searches global handbook, not duty-station statutory overrides). |
| **`get_jurisdiction_rules`** | Retrieves statutory duty-station guidelines, public holiday entitlements, and local statutory baselines. | `jurisdiction: JurisdictionEnum` (`'Kenya'`, `'Ireland'`, `'Cote d\'Ivoire'`, `'Rwanda'`, `'Global'`), `policy_category: PolicyCategoryEnum` (`'leave'`, `'notice_and_separation'`, `'benefits_and_pension'`, `'holidays_and_working_hours'`, `'conduct_and_discipline'`) | `get_employee_record` & `search_handbook` (strictly uses typed enums for geographic duty stations rather than open-ended queries or employee IDs). |

## 3. Tool Definition JSON Schema
```json
{
  "name": "get_jurisdiction_rules",
  "description": "Retrieve jurisdiction-specific statutory rules, public holiday entitlements, local statutory compliance baselines, and duty-station guidelines for a specified jurisdiction and policy category. Use this tool for duty station statutory context.",
  "parameters": {
    "type": "object",
    "properties": {
      "jurisdiction": {
        "type": "string",
        "enum": ["Kenya", "Ireland", "Cote d'Ivoire", "Rwanda", "Global"],
        "description": "The duty station jurisdiction."
      },
      "policy_category": {
        "type": "string",
        "enum": ["leave", "notice_and_separation", "benefits_and_pension", "holidays_and_working_hours", "conduct_and_discipline"],
        "description": "The specific policy category to retrieve."
      }
    },
    "required": ["jurisdiction", "policy_category"]
  }
}
```
