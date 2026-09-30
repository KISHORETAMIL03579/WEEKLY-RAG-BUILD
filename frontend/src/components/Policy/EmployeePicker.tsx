import React, { useId } from "react";
import { EmployeeRecord } from "../../types/policy";

interface EmployeePickerProps {
  employees: readonly EmployeeRecord[];
  value: string;
  onChange: (employeeId: string) => void;
  disabled?: boolean;
  /** Whether any document is indexed (affects the wording of the fallback note). */
  hasDocuments: boolean;
  employeesError?: string | null;
  label?: string;
  className?: string;
}

function describe(employee: EmployeeRecord): string {
  const extra = [
    employee.name,
    employee.jurisdiction,
    employee.employment_status,
  ].filter((part): part is string => typeof part === "string" && !!part);
  return extra.length > 0
    ? `${employee.employee_id} — ${extra.join(" · ")}`
    : employee.employee_id;
}

/**
 * Employee chooser fed by the roster the backend parsed from the uploaded records
 * (GET /api/policy/employees). Without a roster it falls back to a free-text id.
 */
export const EmployeePicker: React.FC<EmployeePickerProps> = ({
  employees,
  value,
  onChange,
  disabled = false,
  hasDocuments,
  employeesError,
  label = "Employee",
  className,
}) => {
  const id = useId();
  const noteId = useId();
  const hasRoster = employees.length > 0;
  const selected = employees.find((e) => e.employee_id === value);

  return (
    <div className={`field${className ? ` ${className}` : ""}`}>
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      {hasRoster ? (
        <select
          id={id}
          className="field-select"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        >
          {!selected && value && (
            <option value={value} disabled>
              {value} (not in roster)
            </option>
          )}
          {employees.map((employee) => (
            <option key={employee.employee_id} value={employee.employee_id}>
              {describe(employee)}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          className="field-input"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          placeholder="Employee ID"
          autoComplete="off"
          spellCheck={false}
          aria-describedby={noteId}
        />
      )}
      {hasRoster ? (
        selected && (
          <div className="field-hint" id={noteId}>
            {[
              selected.job_title,
              selected.department,
              selected.duty_station,
              typeof selected.tenure_months === "number"
                ? `${selected.tenure_months} months tenure`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        )
      ) : (
        <div className="field-hint" id={noteId}>
          {employeesError
            ? employeesError
            : hasDocuments
              ? "No employee roster was found in the uploaded documents, so type the employee ID exactly as it appears in your records file."
              : "Upload the employee records to pick from the roster; until then type an employee ID."}
        </div>
      )}
    </div>
  );
};
