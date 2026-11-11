/**
 * The UI's billing/admin types and readers against the runtime's pinned response shapes
 * (docs/billing/api_shapes.json, written by services/runtime/tests/test_billing_contract.py).
 *
 * 1. Keys: every key the runtime sends is in the UI's type (src/lib/billing-wire.ts, which tsc ties to the types), and
 *    every key in the type is one the runtime sends. 2. Readers: a response built from the shape goes through the reader
 *    the app uses, and each value comes out where the reader puts it (so a reader reading the wrong key fails).
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  readAccount, readActionResult, readAnalytics, readAuditList, readBug, readBugs, readCode, readCodes, readMetrics, readPlan, readPlans,
  readScreenshot, readUserDetail, readUserList,
} from "../../src/lib/admin.ts";
import { OPAQUE, OPTIONAL, WIRE } from "../../src/lib/billing-wire.ts";
import { parseBillingRefusal } from "../../src/lib/plan-limit.ts";

type Shape = string | Shape[] | { [k: string]: Shape };
const SHAPES = JSON.parse(readFileSync(new URL("../../../../docs/billing/api_shapes.json", import.meta.url), "utf8")) as Record<string, Shape>;

/** The admin action's answers differ by action: one key set covers them all. */
function merged(): Record<string, Shape> {
  const out: Record<string, Shape> = {};
  for (const [name, shape] of Object.entries(SHAPES)) {
    const base = name.replace(/ \((extend_trial|send_portal_link|apply_code)\)$/, "");
    out[base] = base in out && base !== name ? { ...(out[base] as object), ...(shape as object) } : shape;
  }
  return out;
}
const ALL = merged();

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** Differences between the UI's key spec and the runtime's shape, as readable paths. */
function diff(spec: unknown, shape: Shape, path: string, out: string[]): void {
  if (spec === true) {
    if (Array.isArray(shape) && (shape.length === 0 || typeof shape[0] === "string")) return; // a list of values (plan_codes)
    if (typeof shape !== "string") out.push(`${path}: the runtime sends an object or list; the UI reads a value`);
    return;
  }
  if (Array.isArray(spec)) {
    if (!Array.isArray(shape)) return void out.push(`${path}: the UI reads a list; the runtime sends ${JSON.stringify(shape)}`);
    if (shape.length === 0) return void out.push(`${path}: the snapshot has an empty list; give the contract test an item`);
    return diff(spec[0], shape[0], `${path}[]`, out);
  }
  if (!isObj(spec)) return void out.push(`${path}: bad spec`);
  if (typeof shape === "string" && shape.split("|").every((t) => t === "null")) return; // e.g. stripe: null in a snapshot
  if (!isObj(shape)) return void out.push(`${path}: the UI reads an object; the runtime sends ${JSON.stringify(shape)}`);
  if (OPAQUE.has(path)) return;
  for (const k of Object.keys(shape)) if (!(k in spec)) out.push(`${path}.${k}: sent by the runtime, missing from the UI's type`);
  for (const [k, sub] of Object.entries(spec)) {
    if (!(k in shape)) {
      if (!OPTIONAL.has(`${path}.${k}`)) out.push(`${path}.${k}: in the UI's type, not sent by the runtime`);
      continue;
    }
    diff(sub, shape[k], `${path}.${k}`, out);
  }
}

test("every endpoint in the snapshot has a UI type, and every UI type an endpoint", () => {
  assert.deepEqual(Object.keys(ALL).sort(), Object.keys(WIRE).sort());
});

for (const name of Object.keys(WIRE).sort()) {
  test(`keys match the runtime: ${name}`, () => {
    const problems: string[] = [];
    if (ALL[name] !== undefined) diff(WIRE[name], ALL[name], name, problems);
    assert.deepEqual(problems, []);
  });
}

// ---- readers -------------------------------------------------------------------------------------------------------

/** A response with a distinct value at every leaf: strings "s<n>", numbers n, booleans true (null where the snapshot only saw null). */
function sample(shape: Shape, n = { i: 1 }): unknown {
  if (Array.isArray(shape)) return shape.length ? [sample(shape[0], n)] : [];
  if (typeof shape === "string") {
    const types = shape.split("|").filter((t) => t !== "null");
    if (types.length === 0) return null; // always null in the snapshot (nothing set in the fixture)
    const t = types[0];
    n.i += 1;
    return t === "number" ? n.i : t === "boolean" ? true : `s${n.i}`;
  }
  return Object.fromEntries(Object.entries(shape).map(([k, v]) => [k, sample(v, n)]));
}

/** Every leaf of `input` (outside opaque objects) shows up at the same path in `output` (numbers may become text). */
function carried(input: unknown, output: unknown, path: string, out: string[]): void {
  if (Array.isArray(input)) {
    if (!Array.isArray(output) || output.length !== input.length) return void out.push(`${path}: list lost`);
    input.forEach((v, i) => carried(v, output[i], `${path}[]`, out));
    return;
  }
  if (isObj(input)) {
    if (!isObj(output)) return void out.push(`${path}: object lost`);
    if (path.endsWith(".detail") && path.includes("audit")) return;
    for (const [k, v] of Object.entries(input)) carried(v, output[k], `${path}.${k}`, out);
    return;
  }
  if (input !== output && String(input) !== String(output)) out.push(`${path}: sent ${JSON.stringify(input)}, read ${JSON.stringify(output)}`);
}

const READERS: Record<string, (raw: unknown) => unknown> = {
  "GET /plans": readPlans,
  "GET /admin/metrics": readMetrics,
  "GET /admin/users": readUserList,
  "GET /admin/users/{id}": readUserDetail,
  "PATCH /admin/users/{id}": readAccount,
  "POST /admin/users/{id}/actions": readActionResult,
  "GET /admin/codes": readCodes,
  "POST /admin/codes": readCode,
  "PATCH /admin/codes/{code}": readCode,
  "GET /admin/plans": readPlans,
  "PATCH /admin/plans/{code}": readPlan,
  "GET /admin/audit": readAuditList,
  "GET /admin/analytics": readAnalytics,
  "GET /admin/bug-reports": readBugs,
  "PATCH /admin/bug-reports/{id}": readBug,
  "GET /admin/bug-reports/{id}/screenshot": readScreenshot,
  "402 plan_limit": (raw) => parseBillingRefusal(402, JSON.stringify(raw)),
  "402 read_only": (raw) => parseBillingRefusal(402, JSON.stringify(raw)),
};

/** Values the readers settle on purpose rather than pass through. */
const FIXED: Record<string, (raw: Record<string, unknown>) => void> = {
  "402 plan_limit": (r) => void (r.code = "plan_limit"),
  "402 read_only": (r) => void (r.code = "read_only"),
};

for (const [name, read] of Object.entries(READERS)) {
  test(`the reader picks up every value: ${name}`, () => {
    const raw = sample(ALL[name]) as Record<string, unknown>;
    FIXED[name]?.(raw);
    const problems: string[] = [];
    carried(raw, read(raw), name, problems);
    assert.deepEqual(problems, []);
  });
}

test("Stripe times in the user detail are seconds since 1970, and a null Stripe summary stays null", () => {
  const d = readUserDetail({ account: {}, stripe: null });
  assert.equal(d.stripe, null);
  assert.equal(d.usage_history.length, 0);
});
