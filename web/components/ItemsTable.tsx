"use client";

import { useMemo, useState } from "react";
import type { PublicVerdict } from "@/lib/artifacts";

// README.md: the golden corpus is 120 public + 180 private items. The explorer's copy states
// that denominator regardless of how many placeholder rows this demo file happens to carry --
// an empty search result must read as "nothing was measured", never a bare "no results".
const PUBLIC_SPLIT_SIZE = 120;

interface ItemSummary {
  itemId: string;
  fields: PublicVerdict[];
  failureModes: string[];
}

function summarize(verdicts: PublicVerdict[]): ItemSummary[] {
  const byItem = new Map<string, PublicVerdict[]>();
  for (const v of verdicts) {
    const fields = byItem.get(v.item_id) ?? [];
    fields.push(v);
    byItem.set(v.item_id, fields);
  }
  return Array.from(byItem.entries()).map(([itemId, fields]) => ({
    itemId,
    fields,
    // Failure mode is `reason` alone (see task-46-report.md): `injected_error` would be the
    // richer signal but is generated in-memory by golden/generate.py and never persisted by
    // golden/build.py, so it isn't available to any published artifact.
    failureModes: Array.from(new Set(fields.filter((f) => !f.correct).map((f) => f.reason))),
  }));
}

interface ItemsTableProps {
  verdicts: PublicVerdict[];
}

export function ItemsTable({ verdicts }: ItemsTableProps) {
  const items = useMemo(() => summarize(verdicts), [verdicts]);
  const failureModes = useMemo(
    () => Array.from(new Set(items.flatMap((item) => item.failureModes))).sort(),
    [items],
  );

  const [search, setSearch] = useState("");
  const [failureMode, setFailureMode] = useState("");

  const term = search.trim().toLowerCase();
  const filtered = items.filter((item) => {
    const matchesFailureMode = failureMode === "" || item.failureModes.includes(failureMode);
    const matchesSearch =
      term === "" ||
      item.itemId.toLowerCase().includes(term) ||
      item.fields.some((f) => f.field_name.toLowerCase().includes(term));
    return matchesFailureMode && matchesSearch;
  });

  return (
    <>
      <div className="items-controls">
        <div className="items-controls__field">
          <label htmlFor="failure-mode-filter">Failure mode</label>
          <select
            id="failure-mode-filter"
            value={failureMode}
            onChange={(event) => setFailureMode(event.target.value)}
          >
            <option value="">All failure modes</option>
            {failureModes.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </select>
        </div>
        <div className="items-controls__field">
          <label htmlFor="item-search">Search</label>
          <input
            id="item-search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Item id or field name"
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="empty-state" role="status" data-testid="empty-state">
          No items match {search ? `"${search}"` : "the selected failure mode"} (0 of{" "}
          {PUBLIC_SPLIT_SIZE} public items).
        </p>
      ) : (
        <table className="report-table items-table">
          <caption className="visually-hidden">Public split item explorer</caption>
          <thead>
            <tr>
              <th scope="col">Item</th>
              <th scope="col">Fields</th>
              <th scope="col">Failure mode(s)</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => (
              <tr key={item.itemId} data-testid="item-row">
                <th scope="row" className="tabular">
                  {item.itemId}
                </th>
                <td>
                  <ul className="items-table__fields">
                    {item.fields.map((field) => (
                      <li key={`${field.slot}-${field.field_name}`}>
                        <span className="tabular">{field.field_name}</span> ({field.slot}):{" "}
                        {field.correct ? "correct" : field.reason}
                      </li>
                    ))}
                  </ul>
                </td>
                <td>{item.failureModes.length > 0 ? item.failureModes.join("; ") : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
