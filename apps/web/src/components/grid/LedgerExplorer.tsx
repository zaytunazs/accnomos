"use client";

import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import type { AccountInfo } from "@azure/msal-browser";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, GridApi, RowClassParams, RowStyle, ValueFormatterParams } from "ag-grid-community";
import { accnomosGridTheme } from "@/components/grid/theme";
import { Gate, Notes, button, card, input, quiet, useLoad } from "@/components/accounting/Shared";
import { accounting, type RtFoundLine } from "@/lib/accounting";
import { LEDGER_COLUMNS, poundsText, poundsValue, sumPence, validateGridFilter } from "@/lib/grid-core";
import { usePowerGridOn } from "@/lib/power-grid";
import { runtime, ukDate } from "@/lib/runtime";

interface Row extends RtFoundLine {
  amount_pence: number;
  pinned?: boolean;
}

const EXAMPLES = ["PayPal fees over £5 in October", "Sales over £500 this year, biggest first", "Anything with no VAT code in September"];

const money = (key: "debit_pence" | "credit_pence" | "amount_pence") => (p: ValueFormatterParams<Row>) =>
  p.data && (p.data[key] || p.data.pinned) ? poundsText(p.data[key]) : "";

function todayLondon(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/London" }).format(new Date());
}

/**
 * Reports › Ledger explorer (Power grid add-on): the newest 500 journal lines from GET /accounting/recode/search in an
 * AG Grid, sorted by account then date so each account's lines sit together (a rule marks where the account changes;
 * row grouping is an Enterprise feature, so it is not used). The box above turns plain words into a filter: the
 * runtime's AI proposes a filter model and sort (POST /ai/grid-filter), the runtime and lib/grid-core.ts both check it
 * against the columns and operators allowed, and only then is it applied. If the AI is not available the words become
 * a quick search. Nothing here changes the books.
 */
export default function LedgerExplorer() {
  const on = usePowerGridOn();
  const load = useCallback(async (a: AccountInfo) => accounting.search(a, {}), []);
  const { account, data, error, setError, note, setNote } = useLoad(load);
  const api = useRef<GridApi<Row> | null>(null);
  const [ask, setAsk] = useState("");
  const [quick, setQuick] = useState("");
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);
  const [totals, setTotals] = useState<Row[]>([]);
  const totalsKey = useRef("");

  const rows = useMemo<Row[]>(
    () => (data?.lines ?? []).map((l) => ({ ...l, amount_pence: l.debit_pence || l.credit_pence })),
    [data],
  );
  const accountNames = useMemo(() => [...new Set(rows.map((r) => r.account))].slice(0, 300), [rows]);

  const columns = useMemo<ColDef<Row>[]>(
    () => [
      {
        field: "account",
        headerName: "Account",
        sort: "asc",
        sortIndex: 0,
        minWidth: 200,
        flex: 1,
        cellStyle: { fontWeight: 700 },
      },
      {
        field: "date",
        headerName: "Date",
        cellDataType: "dateString",
        filter: "agDateColumnFilter",
        filterParams: { inRangeInclusive: true },
        valueFormatter: (p) => (p.data?.pinned || !p.value ? "" : ukDate(p.value)),
        sort: "asc",
        sortIndex: 1,
        width: 130,
      },
      { field: "counterparty", headerName: "Payee or customer", minWidth: 160, flex: 1 },
      { field: "memo", headerName: "Description", minWidth: 200, flex: 2, tooltipField: "memo" },
      { field: "kind", headerName: "Entry type", width: 140 },
      { field: "vat_code", headerName: "VAT", width: 90 },
      ...(["debit", "credit", "amount"] as const).map(
        (c): ColDef<Row> => ({
          colId: c,
          headerName: { debit: "Debit", credit: "Credit", amount: "Amount" }[c],
          valueGetter: (p) => (p.data ? poundsValue(p.data[`${c}_pence`]) : null),
          valueFormatter: money(`${c}_pence`),
          filter: "agNumberColumnFilter",
          type: "rightAligned",
          cellClass: "tabular-nums",
          width: 125,
        }),
      ),
    ],
    [],
  );
  const defaultColDef = useMemo<ColDef<Row>>(() => ({ sortable: true, filter: true, resizable: true, floatingFilter: true }), []);

  const refreshTotals = useCallback(() => {
    const a = api.current;
    if (!a) return;
    const shown: Row[] = [];
    a.forEachNodeAfterFilter((n) => {
      if (n.data) shown.push(n.data);
    });
    const debit = sumPence(shown.map((r) => r.debit_pence));
    const credit = sumPence(shown.map((r) => r.credit_pence));
    const key = `${shown.length}:${debit}:${credit}`;
    if (key === totalsKey.current) return;
    totalsKey.current = key;
    setTotals([
      {
        event_id: "__total",
        line: 0,
        date: "",
        kind: "",
        counterparty: null,
        memo: `Debit − credit: ${poundsText(debit - credit)}`,
        account: `Total of ${shown.length} lines shown`,
        vat_code: null,
        debit_pence: debit,
        credit_pence: credit,
        amount_pence: 0,
        recoded: false,
        recodable: false,
        vat_recodable: false,
        reason: null,
        pinned: true,
      },
    ]);
  }, []);

  /** A heavier rule above the first line of each account while the grid is sorted by account. */
  const rowStyle = useCallback((p: RowClassParams<Row>): RowStyle | undefined => {
    const idx = p.node.rowIndex;
    if (p.node.rowPinned || idx === null || idx === 0) return undefined;
    const prev = p.api.getDisplayedRowAtIndex(idx - 1)?.data;
    return prev && prev.account !== p.data?.account ? { borderTop: "2px solid var(--color-teal)" } : undefined;
  }, []);

  function clearAll() {
    api.current?.setFilterModel(null);
    api.current?.applyColumnState({
      state: [
        { colId: "account", sort: "asc", sortIndex: 0 },
        { colId: "date", sort: "asc", sortIndex: 1 },
      ],
      defaultState: { sort: null },
    });
    setQuick("");
    setApplied(null);
    setNote(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const text = ask.trim();
    const a = api.current;
    if (!text || !account || !a) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const r = await runtime.gridFilter(account, { grid: "ledger", text, today: todayLondon(), accounts: accountNames });
      const v = validateGridFilter(r.filter_model, r.sort, LEDGER_COLUMNS);
      const dropped = [...r.dropped, ...v.dropped];
      const anything = Object.keys(v.filterModel).length > 0 || v.sort.length > 0;
      a.setFilterModel(v.filterModel);
      if (v.sort.length) {
        a.applyColumnState({ state: v.sort.map((s, i) => ({ colId: s.colId, sort: s.sort, sortIndex: i })), defaultState: { sort: null } });
      }
      const fallback = !anything || r.quick_filter ? (r.quick_filter ?? text) : "";
      setQuick(fallback);
      setApplied(
        anything
          ? `${r.summary || "Filter applied"}${fallback ? ` · also searching for "${fallback}"` : ""}`
          : `Searching every column for "${fallback}"${r.fallback_reason ? ` (${r.fallback_reason})` : ""}`,
      );
      if (dropped.length) setNote(`Left out because they are not allowed here: ${dropped.join(", ")}.`);
    } catch (err) {
      a.setFilterModel(null);
      setQuick(text);
      setApplied(`Searching every column for "${text}" (the AI filter is not available: ${(err as Error).message})`);
    } finally {
      setBusy(false);
    }
  }

  if (!on)
    return (
      <p className="rounded-2xl border border-border bg-white p-5 text-[15px]">
        The ledger explorer is part of the Power grid add-on.{" "}
        <Link href="/settings#settings-power-grid" className="font-bold text-teal-dark underline">
          Turn it on in Settings
        </Link>
      </p>
    );

  return (
    <Gate account={account} ready={!!data || !!error} what="to explore every journal line in your ledger.">
      <div className="flex min-w-0 flex-col gap-4">
        <Notes note={note} error={error} />
        <section aria-labelledby="ledger-ask" className={card}>
          <h2 id="ledger-ask" className="text-[17px] font-extrabold">Show me…</h2>
          <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => void submit(e)}>
            <label htmlFor="ledger-ask-text" className="sr-only">Describe the lines you want to see</label>
            <input
              id="ledger-ask-text"
              className={`${input} flex-1`}
              maxLength={300}
              placeholder={`e.g. ${EXAMPLES[0]}`}
              value={ask}
              onChange={(e) => setAsk(e.target.value)}
            />
            <button type="submit" className={button} disabled={busy || !ask.trim()}>
              {busy ? "Working it out…" : "Filter"}
            </button>
            <button type="button" className={quiet} onClick={clearAll}>Clear</button>
            <button
              type="button"
              className={quiet}
              onClick={() => api.current?.exportDataAsCsv({ fileName: "ledger-lines.csv", skipPinnedBottom: false })}
            >
              Export CSV
            </button>
          </form>
          <p className="mt-2 text-[13px] text-muted">
            Your AI only proposes a filter and a sort, checked against the columns before it is used; it cannot change your
            books. Try: {EXAMPLES.map((x, i) => (
              <span key={x}>
                <button type="button" className="font-bold text-teal-dark underline" onClick={() => setAsk(x)}>{x}</button>
                {i < EXAMPLES.length - 1 ? " · " : ""}
              </span>
            ))}
          </p>
          {applied && <p role="status" className="mt-2 rounded-xl bg-teal-tint px-4 py-2 text-sm font-bold text-teal-dark">{applied}</p>}
          {data?.truncated && <p className="mt-2 text-sm text-muted">Showing the newest 500 lines.</p>}
        </section>
        <section aria-label="Ledger lines" data-testid="ledger-grid" style={{ height: 620, width: "100%" }}>
          <AgGridReact<Row>
            theme={accnomosGridTheme}
            rowData={rows}
            columnDefs={columns}
            defaultColDef={defaultColDef}
            getRowId={(p) => `${p.data.event_id}:${p.data.line}`}
            pinnedBottomRowData={totals}
            quickFilterText={quick}
            getRowStyle={rowStyle}
            tooltipShowDelay={300}
            onGridReady={(e) => {
              api.current = e.api;
              refreshTotals();
            }}
            onModelUpdated={(e) => {
              refreshTotals();
              e.api.redrawRows(); // the account rules follow the new order
            }}
          />
        </section>
      </div>
    </Gate>
  );
}
