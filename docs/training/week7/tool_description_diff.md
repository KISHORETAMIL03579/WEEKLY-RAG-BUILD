# Tool Description & Architecture Diff: Third Tool Addition

## 1. Summary of Changes

In Week 7, a third tool `get_jurisdiction_rules` was added to the tool catalog alongside `get_employee_record` and `search_handbook` to support duty station statutory lookup.

## 2. Tool Separation & Non-Overlap Matrix

| Tool Name                            | Exact Responsibility                                                                                      | Parameter Types & Enums                                                                                                                                                                                                                                                   | Prevents Overlap With                                                                                                                                  |
| :----------------------------------- | :-------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`get_employee_record`**            | Retrieves individual employee profile attributes (tenure, status, salary, department, separation reason). | `employee_id: str`                                                                                                                                                                                                                                                        | `search_handbook` (does not search policy text); `get_jurisdiction_rules` (does not return employee records).                                          |
| **`search_handbook`**                | Performs keyword / semantic search against the global organization HRPPM policy manual text.              | `query: str`, `top_k: int`                                                                                                                                                                                                                                                | `get_employee_record` (does not look up employee profiles); `get_jurisdiction_rules` (searches global handbook, not duty-station statutory overrides). |
| **`get_jurisdiction_rules`** _(NEW)_ | Retrieves the policy rule for one specified jurisdiction and policy category. | `jurisdiction: JurisdictionEnum` (`'Kenya'`, `'Ireland'`, `'Cote d\'Ivoire'`, `'Rwanda'`, `'Global'`), `policy_category: PolicyCategoryEnum` (`'leave'`, `'notice_and_separation'`, `'benefits_and_pension'`, `'holidays_and_working_hours'`, `'conduct_and_discipline'`) | `get_employee_record` (profile lookup) and `search_handbook` (organization-wide handbook search). |

## 3. Tool Definition JSON Schema

```json
{
  "name": "get_jurisdiction_rules",
  "description": "Retrieve the policy rule for one specified jurisdiction and policy category.",
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
        "enum": [
          "leave",
          "notice_and_separation",
          "benefits_and_pension",
          "holidays_and_working_hours",
          "conduct_and_discipline"
        ],
        "description": "The specific policy category to retrieve."
      }
    },
    "required": ["jurisdiction", "policy_category"]
  }
}
```
