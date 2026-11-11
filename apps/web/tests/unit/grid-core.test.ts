import assert from "node:assert/strict";
import { test } from "node:test";
import { LEDGER_COLUMNS, penceTotals, poundsText, sumPence, validateGridFilter } from "../../src/lib/grid-core.ts";

test("a good filter from the runtime passes through, rebuilt", () => {
  const v = validateGridFilter(
    {
      counterparty: { filterType: "text", type: "contains", filter: " PayPal " },
      amount: { filterType: "number", type: "greaterThan", filter: 5 },
      date: { filterType: "date", type: "inRange", dateFrom: "2026-10-01 00:00:00", dateTo: "2026-10-31 00:00:00" },
    },
    [{ colId: "amount", sort: "desc" }],
  );
  assert.deepEqual(v.dropped, []);
  assert.deepEqual(v.filterModel, {
    counterparty: { filterType: "text", type: "contains", filter: "PayPal" },
    amount: { filterType: "number", type: "greaterThan", filter: 5 },
    date: { filterType: "date", type: "inRange", dateFrom: "2026-10-01 00:00:00", dateTo: "2026-10-31 00:00:00" },
  });
  assert.deepEqual(v.sort, [{ colId: "amount", sort: "desc" }]);
});

test("unknown columns, operators, kinds and bad values are dropped and named", () => {
  const v = validateGridFilter(
    {
      secret: { filterType: "text", type: "contains", filter: "x" },
      memo: { filterType: "number", type: "greaterThan", filter: 5 }, // wrong kind for the column
      account: { filterType: "text", type: "regex", filter: ".*" },
      debit: { filterType: "number", type: "greaterThan", filter: "lots" },
      credit: { filterType: "number", type: "inRange", filter: 50, filterTo: 5 },
      date: { filterType: "date", type: "equals", dateFrom: "2026-02-30" },
      kind: { filterType: "text", type: "contains", filter: "x".repeat(101) },
      vat_code: { filterType: "text", type: "equals", filter: "S", onFilter: "alert(1)" },
    },
    [{ colId: "nope", sort: "asc" }, { colId: "date", sort: "sideways" }, { colId: "date", sort: "asc" }],
  );
  assert.deepEqual(v.filterModel, { vat_code: { filterType: "text", type: "equals", filter: "S" } });
  assert.deepEqual(v.sort, [{ colId: "date", sort: "asc" }]);
  assert.ok(v.dropped.includes("column secret"));
  assert.equal(v.dropped.filter((d) => d === "a sort").length, 2);
  assert.equal(Object.getPrototypeOf(v.filterModel), Object.prototype);
});

test("a __proto__ key from JSON is just an unknown column", () => {
  const v = validateGridFilter(JSON.parse('{"__proto__": {"filterType": "text", "type": "contains", "filter": "x"}}'), []);
  assert.deepEqual(v.filterModel, {});
  assert.deepEqual(v.dropped, ["column __proto__"]);
  assert.equal(Object.getPrototypeOf(v.filterModel), Object.prototype);
});

test("combined conditions: at most two, all valid, AND or OR", () => {
  const c = { filterType: "number", type: "greaterThan", filter: 5 };
  const ok = validateGridFilter({ amount: { filterType: "number", operator: "AND", conditions: [c, { ...c, type: "lessThan", filter: 50 }] } }, []);
  assert.equal((ok.filterModel.amount as { conditions: unknown[] }).conditions.length, 2);
  const three = validateGridFilter({ amount: { filterType: "number", operator: "AND", conditions: [c, c, c] } }, []);
  assert.deepEqual(three.filterModel, {});
  const badOp = validateGridFilter({ amount: { filterType: "number", operator: "XOR", conditions: [c] } }, []);
  assert.deepEqual(badOp.filterModel, {});
});

test("non-objects are refused", () => {
  assert.deepEqual(validateGridFilter("drop table", "x").filterModel, {});
  assert.deepEqual(validateGridFilter(null, null), { filterModel: {}, sort: [], dropped: [] });
  assert.deepEqual(validateGridFilter([], []).dropped, ["filter (not an object)"]);
  assert.equal(LEDGER_COLUMNS.length, 9);
});

test("pence totals add integers exactly (no float drift)", () => {
  const rows = Array.from({ length: 1000 }, () => ({ gross_pence: 10, fee_pence: 20, net_pence: -10 }));
  assert.deepEqual(penceTotals(rows), { gross_pence: 10000, fee_pence: 20000, net_pence: -10000 });
  // 0.1 + 0.2 in pounds would drift; in pence it is exact
  assert.equal(sumPence([10, 20]), 30);
  assert.throws(() => sumPence([1.5]));
  assert.throws(() => sumPence([Number.MAX_SAFE_INTEGER, 1]));
});

test("pounds text from pence", () => {
  assert.equal(poundsText(0), "£0.00");
  assert.equal(poundsText(5), "£0.05");
  assert.equal(poundsText(123456789), "£1,234,567.89");
  assert.equal(poundsText(-500), "−£5.00");
});
