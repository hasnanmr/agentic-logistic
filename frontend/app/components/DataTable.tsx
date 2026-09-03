import type { QueryResult, Scalar } from "@/lib/types";

interface DataTableProps {
  result: QueryResult;
}

function renderCell(value: Scalar): string {
  if (value === null) return "N/A";
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  return String(value);
}

export default function DataTable({ result }: DataTableProps) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            {result.columns.map((column) => (
              <th key={column} scope="col">
                {column.replaceAll("_", " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className={cell === null ? "cell-null" : undefined}>
                  {renderCell(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
