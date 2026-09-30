import React from "react";

export interface DataColumn<T> {
  key: string;
  header: React.ReactNode;
  render: (row: T, index: number) => React.ReactNode;
  align?: "left" | "center" | "right";
  /** Truncate long text with an ellipsis (set a title inside `render` for the full text). */
  clip?: boolean;
  headerTitle?: string;
  width?: string | number;
}

interface DataTableProps<T> {
  columns: readonly DataColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T, index: number) => string;
  caption?: React.ReactNode;
  ariaLabel?: string;
  dense?: boolean;
  empty?: React.ReactNode;
}

/** Shared .clean-table wrapper: horizontal scroll, dense mode, empty state. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  ariaLabel,
  dense = true,
  empty = "No rows.",
}: DataTableProps<T>): React.ReactElement {
  const alignClass = (align?: DataColumn<T>["align"]) =>
    align === "center" ? "is-center" : align === "right" ? "is-right" : "";

  return (
    <div className="table-scroll">
      <table
        className={`clean-table${dense ? " is-dense" : ""}`}
        aria-label={ariaLabel}
      >
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                title={column.headerTitle}
                className={alignClass(column.align)}
                style={column.width ? { width: column.width } : undefined}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="table-empty">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr key={rowKey(row, index)}>
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={[
                      alignClass(column.align),
                      column.clip ? "cell-clip" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {column.render(row, index)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
