"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import { AgGridReact } from "ag-grid-react";
import type { CellValueChangedEvent, ColDef, GridApi, ValueFormatterParams } from "ag-grid-community";
import { accnomosGridTheme } from "@/components/grid/theme";
import { COST_ACCOUNTS, KIND, PURCHASE_VAT, VAT_CODES } from "@/components/invoices/paypal-codes";
import { primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { RuntimeErrorNote } from "@/components/States";
import { penceTotals, poundsText, poundsValue } from "@/lib/grid-core";
import { runtime, ukDate, type RtPaypalSyncItem } from "@/lib/runtime";

const TOTAL_ID = "__total";

interface Row extends RtPaypalSyncItem {
  /** The account and VAT code the user sees (the AI's suggestion until edited). */
  edit_account: string | null;
  edit_vat: string | null;
  no_receipt: string;
  result: string;
}

const STATUS: Record<RtPaypalSyncItem["status"], string> = {
  proposed: "Waiting",
  approved: "Approved",
  rejected: "Rejected",
  already: "Already in your books",
  info: "Not posted",
};

const editableRow = (r: Row | undefined) => !!r && r.transaction_id !== TOTAL_ID && r.status === "proposed" && r.kind === "expense";

function money(field: "gross_pence" | "fee_pence" | "net_pence") {
  return (p: ValueFormatterParams<Row>) => {
    const r = p.data;
    if (!r) return "";
    if (r.currency !== "GBP") return `${(r[field] / 100).toFixed(2)} ${r.currency}`;
    return poundsText(r[field]);
  };
}

/**
 * Power grid on the PayPal panel: every synced PayPal transaction in one sortable, filterable grid. Tick the waiting
 * ones, change the AI's account or VAT code in the cell, and "Approve selected" posts them one at a time through the
 * same POST /payments/paypal/sync/{id}/approve the card list uses, after one confirmation. Rows not ticked are never
 * sent; rows that are not waiting cannot be ticked.
 */
export default function PayPalReviewGrid({
  account,
  items,
  onChanged,
}: {
  account: AccountInfo;
  items: RtPaypalSyncItem[];
  onChanged: (item: RtPaypalSyncItem, message: string) => void;
}) {
  const api = useRef<GridApi<Row> | null>(null);
  const [edits, setEdits] = useState<Record<string, { account: string | null; vat: string | null }>>({});
  const [results, setResults] = useState<Record<string, string>>({});
  const [quick, setQuick] = useState("");
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [totals, setTotals] = useState<Row[]>([]);
  const totalsKey = useRef("");

  const rows = useMemo<Row[]>(
    () =>
      items.map((i) => ({
        ...i,
        edit_account: edits[i.transaction_id]?.account ?? i.account,
        edit_vat: edits[i.transaction_id]?.vat ?? i.vat_code ?? (i.kind === "expense" ? "N" : null),
        no_receipt: i.notes.some((n) => n.startsWith("No receipt")) ? "No receipt" : "",
        result: results[i.transaction_id] ?? "",
      })),
    [items, edits, results],
  );

  const columns = useMemo<ColDef<Row>[]>(
    () => [
      {
        field: "date",
        headerName: "Date",
        cellDataType: "dateString",
        filter: "agDateColumnFilter",
        filterParams: { inRangeInclusive: true },
        valueFormatter: (p) => (p.data?.transaction_id === TOTAL_ID ? "" : p.value ? ukDate(p.value) : ""),
        width: 120,
        sort: "desc",
      },
      {
        colId: "payee",
        headerName: "Payee / description",
        valueGetter: (p) => (p.data ? [p.data.name, ...p.data.items].filter(Boolean).join(" · ") : ""),
        tooltipValueGetter: (p) => p.value,
        flex: 2,
        minWidth: 200,
      },
      ...(["gross_pence", "fee_pence", "net_pence"] as const).map(
        (f): ColDef<Row> => ({
          colId: f.replace("_pence", ""),
          headerName: { gross_pence: "Gross", fee_pence: "PayPal fee", net_pence: "Net" }[f],
          cellDataType: "number",
          valueGetter: (p) => (p.data ? poundsValue(p.data[f]) : null),
          valueFormatter: money(f),
          filter: "agNumberColumnFilter",
          type: "rightAligned",
          cellClass: "tabular-nums",
          width: 120,
        }),
      ),
      {
        field: "edit_account",
        headerName: "Account (AI)",
        editable: (p) => editableRow(p.data),
        cellEditor: "agSelectCellEditor",
        cellEditorParams: { values: COST_ACCOUNTS },
        cellStyle: (p) => (editableRow(p.data) && p.data?.edit_account !== p.data?.account ? { fontWeight: 800 } : null),
        valueFormatter: (p) => p.value ?? (p.data?.transaction_id === TOTAL_ID ? "" : "—"),
        flex: 1,
        minWidth: 190,
      },
      {
        field: "edit_vat",
        headerName: "VAT (AI)",
        editable: (p) => editableRow(p.data),
        cellEditor: "agSelectCellEditor",
        cellEditorParams: { values: PURCHASE_VAT },
        valueFormatter: (p) => (p.value ? `${p.value} · ${VAT_CODES[p.value as string] ?? ""}` : ""),
        width: 170,
      },
      {
        colId: "kind",
        headerName: "Kind",
        valueGetter: (p) => (p.data && p.data.transaction_id !== TOTAL_ID ? KIND[p.data.kind] : ""),
        width: 150,
      },
      {
        colId: "reason",
        headerName: "Coded by / reason",
        valueGetter: (p) =>
          p.data && p.data.transaction_id !== TOTAL_ID
            ? [p.data.coded_by ? `Coded by ${p.data.coded_by}` : "", ...p.data.notes].filter(Boolean).join(" · ")
            : "",
        tooltipValueGetter: (p) => p.value,
        flex: 2,
        minWidth: 220,
      },
      {
        field: "no_receipt",
        headerName: "Receipt",
        cellStyle: (p) => (p.value ? { fontWeight: 800, color: "var(--color-warn-ink)" } : null),
        width: 120,
      },
      {
        colId: "status",
        headerName: "Status",
        valueGetter: (p) => (p.data && p.data.transaction_id !== TOTAL_ID ? STATUS[p.data.status] : ""),
        width: 130,
      },
      {
        field: "result",
        headerName: "Result",
        cellStyle: (p) => (String(p.value ?? "").startsWith("Not approved") ? { fontWeight: 800, color: "var(--color-neg-ink)" } : null),
        tooltipValueGetter: (p) => p.value,
        width: 200,
      },
    ],
    [],
  );

  const defaultColDef = useMemo<ColDef<Row>>(
    () => ({ sortable: true, filter: true, resizable: true, floatingFilter: true, cellDataType: false }),
    [],
  );

  /** The pinned totals row: the GBP rows the filters leave showing, added up in pence. */
  const refreshTotals = useCallback(() => {
    const a = api.current;
    if (!a) return;
    const shown: Row[] = [];
    a.forEachNodeAfterFilter((n) => {
      if (n.data && n.data.currency === "GBP") shown.push(n.data);
    });
    const t = penceTotals(shown);
    const key = `${shown.length}:${t.gross_pence}:${t.fee_pence}:${t.net_pence}`;
    if (key === totalsKey.current) return; // unchanged: no new pinned row, no re-render loop
    totalsKey.current = key;
    setTotals([
      {
        ...({} as RtPaypalSyncItem),
        transaction_id: TOTAL_ID,
        date: "",
        name: `Total of ${shown.length} shown (GBP)`,
        items: [],
        notes: [],
        currency: "GBP",
        ...t,
        edit_account: null,
        edit_vat: null,
        no_receipt: "",
        result: "",
      } as Row,
    ]);
  }, []);

  function edited(e: CellValueChangedEvent<Row>) {
    const r = e.data;
    if (!r || !editableRow(r)) return;
    setEdits((m) => ({ ...m, [r.transaction_id]: { account: r.edit_account, vat: r.edit_vat } }));
  }

  async function approveSelected() {
    const a = api.current;
    if (!a) return;
    const picked = a.getSelectedRows().filter((r) => r.status === "proposed" && r.transaction_id !== TOTAL_ID);
    if (picked.length === 0) return;
    const sum = penceTotals(picked.filter((r) => r.currency === "GBP"));
    const ok = window.confirm(
      `Approve ${picked.length} PayPal transaction${picked.length === 1 ? "" : "s"} (gross ${poundsText(sum.gross_pence)})? ` +
        "Each one is posted to your books, one at a time. Rows you did not tick are left alone.",
    );
    if (!ok) return;
    setBusy(true);
    setError(null);
    setNote(null);
    let done = 0;
    for (const r of picked) {
      const changed = r.kind === "expense" && (r.edit_account !== r.account || r.edit_vat !== r.vat_code);
      const body = changed ? { account: r.edit_account ?? undefined, vat_code: r.edit_vat ?? undefined } : {};
      try {
        const out = await runtime.paypalSyncApprove(account, r.transaction_id, body);
        done += 1;
        setResults((m) => ({ ...m, [r.transaction_id]: changed ? "Approved (your coding)" : "Approved" }));
        onChanged(out, `${KIND[r.kind]} of ${poundsText(Math.abs(r.gross_pence))} (${r.name}) is in your books.`);
      } catch (e) {
        setResults((m) => ({ ...m, [r.transaction_id]: `Not approved: ${(e as Error).message}` }));
      }
    }
    a.deselectAll();
    setBusy(false);
    const failed = picked.length - done;
    setNote(`${done} of ${picked.length} approved${failed ? `; ${failed} not approved (see Result)` : ""}.`);
    if (failed) setError(`${failed} could not be approved. The Result column says why for each.`);
  }

  return (
    <section aria-label="PayPal review grid" className="space-y-2" data-testid="paypal-grid">
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="pp-grid-quick">Search the PayPal grid</label>
        <input
          id="pp-grid-quick"
          type="search"
          placeholder="Search every column"
          value={quick}
          onChange={(e) => setQuick(e.target.value)}
          className="min-h-11 flex-1 rounded-xl border border-border bg-white px-3 text-[15px]"
        />
        <button
          type="button"
          className={secondaryButton}
          onClick={() => api.current?.exportDataAsCsv({ fileName: "paypal-transactions.csv", skipPinnedBottom: false })}
        >
          Export CSV
        </button>
        <button type="button" className={primaryButton} disabled={busy || selected === 0} onClick={() => void approveSelected()}>
          {busy ? "Approving…" : `Approve selected (${selected})`}
        </button>
      </div>
      <p className="text-[13px] text-muted">
        Tick the waiting rows to approve. Account and VAT on purchases can be changed in the cell; the runtime works the
        journal out again when it posts.
      </p>
      <div style={{ width: "100%" }}>
        <AgGridReact<Row>
          theme={accnomosGridTheme}
          rowData={rows}
          columnDefs={columns}
          defaultColDef={defaultColDef}
          getRowId={(p) => p.data.transaction_id}
          rowSelection={{
            mode: "multiRow",
            checkboxes: true,
            headerCheckbox: true,
            enableClickSelection: false,
            isRowSelectable: (n) => n.data?.status === "proposed",
          }}
          pinnedBottomRowData={totals}
          quickFilterText={quick}
          domLayout="autoHeight"
          singleClickEdit
          stopEditingWhenCellsLoseFocus
          tooltipShowDelay={300}
          onGridReady={(e) => {
            api.current = e.api;
            refreshTotals();
          }}
          onModelUpdated={refreshTotals}
          onSelectionChanged={(e) => setSelected(e.api.getSelectedRows().length)}
          onCellValueChanged={edited}
        />
      </div>
      {note && <p role="status" className="rounded-xl bg-teal-tint px-4 py-2 text-sm font-bold text-teal-dark">{note}</p>}
      {error && <RuntimeErrorNote message={error} title="Some were not approved" />}
    </section>
  );
}
