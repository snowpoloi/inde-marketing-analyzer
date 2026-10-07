import { Fragment, type Key, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  sortDirection?: "asc" | "desc" | null;
  onSort?: () => void;
};

export function DataTable<T>({ rows, columns, empty, rowKey, renderExpandedRow }: {
  rows: T[];
  columns: Column<T>[];
  empty: string;
  rowKey?: (row: T) => Key;
  renderExpandedRow?: (row: T) => ReactNode;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={column.align ? `align-${column.align}` : undefined}>
                {column.sortable ? (
                  <button
                    type="button"
                    className={`sortable-header ${column.align ? `align-${column.align}` : ""}`}
                    onClick={column.onSort}
                    aria-label={`Sort by ${column.header}`}
                  >
                    <span>{column.header}</span>
                    {column.sortDirection === "asc" ? (
                      <ArrowUp size={13} />
                    ) : column.sortDirection === "desc" ? (
                      <ArrowDown size={13} />
                    ) : (
                      <ArrowUpDown size={13} />
                    )}
                  </button>
                ) : (
                  column.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="empty-cell">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, index) => {
              const expanded = renderExpandedRow?.(row);
              return <Fragment key={rowKey ? rowKey(row) : index}>
              <tr>
                {columns.map((column) => (
                  <td key={column.key} className={column.align ? `align-${column.align}` : undefined}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
              {expanded != null && <tr className="expanded-table-row"><td colSpan={columns.length}>{expanded}</td></tr>}
              </Fragment>;
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
