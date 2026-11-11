/**
 * Power grid (Settings › Business › Power grid): the pure parts, kept free of React and AG Grid so node --test can run
 * them (tests/unit/grid-core.test.ts).
 *
 * - Money stays in whole pence: totals add integers, never floats; £ text is made from pence at the end.
 * - A filter the AI proposes (POST /ai/grid-filter, services/runtime/app/ai/grid_filter.py) is checked again here
 *   against an allowlist of columns and operators before it reaches grid.setFilterModel / applyColumnState. Anything
 *   not on the list is dropped and named. Filters only ever narrow what is shown: nothing here writes.
 */

export type ColKind = "text" | "number" | "date";

export interface GridColSpec {
  id: string;
  kind: ColKind;
  label: string;
}

/** The ledger explorer's columns (one row per journal line, from GET /accounting/recode/search). Money columns hold
 *  pounds as numbers for filtering; totals use the pence on each row. Keep in step with grid_filter.LEDGER_COLUMNS. */
export const LEDGER_COLUMNS: GridColSpec[] = [
  { id: "date", kind: "date", label: "Date" },
  { id: "account", kind: "text", label: "Account" },
  { id: "counterparty", kind: "text", label: "Payee or customer" },
  { id: "memo", kind: "text", label: "Description" },
  { id: "kind", kind: "text", label: "Entry type" },
  { id: "vat_code", kind: "text", label: "VAT" },
  { id: "debit", kind: "number", label: "Debit" },
  { id: "credit", kind: "number", label: "Credit" },
  { id: "amount", kind: "number", label: "Amount" },
];

export const TEXT_OPS = ["contains", "notContains", "equals", "notEqual", "startsWith", "endsWith"] as const;
export const NUMBER_OPS = ["equals", "notEqual", "greaterThan", "greaterThanOrEqual", "lessThan", "lessThanOrEqual", "inRange"] as const;
export const DATE_OPS = ["equals", "notEqual", "greaterThan", "lessThan", "inRange"] as const;
export const OPS: Record<ColKind, readonly string[]> = { text: TEXT_OPS, number: NUMBER_OPS, date: DATE_OPS };

const TEXT_MAX = 100;
const MONEY_MAX = 100_000_000; // £100m: anything bigger is not a filter a small business means
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

export interface SimpleFilter {
  filterType: ColKind;
  type: string;
  filter?: string | number;
  filterTo?: number;
  dateFrom?: string | null;
  dateTo?: string | null;
}
export interface CombinedFilter {
  filterType: ColKind;
  operator: "AND" | "OR";
  conditions: SimpleFilter[];
}
export type ColumnFilter = SimpleFilter | CombinedFilter;
export type FilterModel = Record<string, ColumnFilter>;
export interface SortItem {
  colId: string;
  sort: "asc" | "desc";
}
export interface ValidatedFilter {
  filterModel: FilterModel;
  sort: SortItem[];
  /** What was dropped, in words (shown under the box). */
  dropped: string[];
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function validDay(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const day = v.slice(0, 10);
  if (!ISO_DAY.test(day)) return null;
  const d = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== day ? null : day;
}

function validNumber(v: unknown): number | null {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) && Math.abs(n) <= MONEY_MAX ? n : null;
}

/** One condition rebuilt from scratch (no key is copied across), or null when it is not allowed. */
function condition(spec: GridColSpec, raw: unknown): SimpleFilter | null {
  if (!isObj(raw)) return null;
  const type = raw.type;
  if (typeof type !== "string" || !OPS[spec.kind].includes(type)) return null;
  if (spec.kind === "text") {
    const f = raw.filter;
    if (typeof f !== "string" || !f.trim() || f.length > TEXT_MAX) return null;
    return { filterType: "text", type, filter: f.trim() };
  }
  if (spec.kind === "number") {
    const f = validNumber(raw.filter);
    if (f === null) return null;
    if (type !== "inRange") return { filterType: "number", type, filter: f };
    const to = validNumber(raw.filterTo);
    return to === null || to < f ? null : { filterType: "number", type, filter: f, filterTo: to };
  }
  const from = validDay(raw.dateFrom);
  if (!from) return null;
  if (type !== "inRange") return { filterType: "date", type, dateFrom: `${from} 00:00:00`, dateTo: null };
  const to = validDay(raw.dateTo);
  return !to || to < from ? null : { filterType: "date", type, dateFrom: `${from} 00:00:00`, dateTo: `${to} 00:00:00` };
}

/**
 * Check a proposed filter model and sort against `columns`: unknown columns, operators, filter kinds and values are
 * dropped (and named in `dropped`). At most two conditions per column (AG Grid's own default) and three sort keys.
 */
export function validateGridFilter(
  rawModel: unknown,
  rawSort: unknown,
  columns: GridColSpec[] = LEDGER_COLUMNS,
): ValidatedFilter {
  const byId = new Map(columns.map((c) => [c.id, c]));
  const filterModel: FilterModel = {};
  const dropped: string[] = [];
  if (rawModel !== null && rawModel !== undefined && !isObj(rawModel)) dropped.push("filter (not an object)");
  for (const [colId, raw] of Object.entries(isObj(rawModel) ? rawModel : {})) {
    const spec = byId.get(colId);
    if (!spec) {
      dropped.push(`column ${colId.slice(0, 40)}`);
      continue;
    }
    if (!isObj(raw) || raw.filterType !== spec.kind) {
      dropped.push(`${spec.label} filter`);
      continue;
    }
    if (Array.isArray(raw.conditions)) {
      const op = raw.operator === "OR" ? "OR" : raw.operator === "AND" ? "AND" : null;
      const conds = raw.conditions.slice(0, 2).map((c) => condition(spec, c));
      if (!op || conds.length === 0 || conds.some((c) => c === null) || raw.conditions.length > 2) {
        dropped.push(`${spec.label} filter`);
        continue;
      }
      filterModel[colId] =
        conds.length === 1 ? (conds[0] as SimpleFilter) : { filterType: spec.kind, operator: op, conditions: conds as SimpleFilter[] };
      continue;
    }
    const c = condition(spec, raw);
    if (c) filterModel[colId] = c;
    else dropped.push(`${spec.label} filter`);
  }
  const sort: SortItem[] = [];
  for (const s of Array.isArray(rawSort) ? rawSort : []) {
    if (!isObj(s) || typeof s.colId !== "string" || !byId.has(s.colId) || (s.sort !== "asc" && s.sort !== "desc")) {
      dropped.push("a sort");
      continue;
    }
    if (sort.length < 3 && !sort.some((x) => x.colId === s.colId)) sort.push({ colId: s.colId, sort: s.sort });
  }
  return { filterModel, sort, dropped };
}

// ---- Money in pence ----------------------------------------------------------------------------------------- //

/** Add whole-pence amounts exactly (integers only; a non-integer is a bug upstream and throws). */
export function sumPence(values: Iterable<number>): number {
  let total = 0;
  for (const v of values) {
    if (!Number.isSafeInteger(v)) throw new Error(`Not a whole number of pence: ${v}`);
    total += v;
  }
  if (!Number.isSafeInteger(total)) throw new Error("Total is too large");
  return total;
}

/** Gross, PayPal fee and net totals of the rows shown, in pence. */
export function penceTotals<T extends { gross_pence: number; fee_pence: number; net_pence: number }>(rows: T[]) {
  return {
    gross_pence: sumPence(rows.map((r) => r.gross_pence)),
    fee_pence: sumPence(rows.map((r) => r.fee_pence)),
    net_pence: sumPence(rows.map((r) => r.net_pence)),
  };
}

/** "£1,234.56", "−£5.00": from pence, by integer division (no float rounding). */
export function poundsText(pence: number): string {
  const neg = pence < 0;
  const p = Math.abs(Math.trunc(pence));
  const pounds = Math.floor(p / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "−" : ""}£${pounds}.${String(p % 100).padStart(2, "0")}`;
}

/** Pounds as a number for the grid's filters and sort only (never added up). */
export const poundsValue = (pence: number): number => pence / 100;
