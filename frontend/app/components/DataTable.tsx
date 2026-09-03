"use client";

import { useMemo, useState } from "react";

import type { QueryResult, Scalar } from "@/lib/types";
import { ArrowUpIcon } from "./icons";

interface DataTableProps {
  result: QueryResult;
}

function renderCell(value: Scalar): string {
  if (value === null) return "N/A";
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  return String(value);
}

function compareValues(a: Scalar, b: Scalar): number {
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

export default function DataTable({ result }: DataTableProps) {
  const [sort, setSort] = useState<{ column: number; direction: "asc" | "desc" } | null>(null);

  const rows = useMemo(() => {
    if (sort === null) return result.rows;
    const sorted = [...result.rows].sort((a, b) => compareValues(a[sort.column], b[sort.column]));
    return sort.direction === "desc" ? sorted.reverse() : sorted;
  }, [result.rows, sort]);

  function toggleSort(column: number) {
    setSort((current) => {
      if (current?.column !== column) return { column, direction: "asc" };
      if (current.direction === "asc") return { column, direction: "desc" };
      return null;
    });
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            {result.columns.map((column, index) => {
              const active = sort?.column === index;
              return (
                <th key={column} scope="col">
                  <button
                    type="button"
                    className="th-sort"
                    data-active={active}
                    data-direction={active ? sort!.direction : undefined}
                    onClick={() => toggleSort(index)}
                  >
                    {column.replaceAll("_", " ")}
                    <ArrowUpIcon />
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
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
