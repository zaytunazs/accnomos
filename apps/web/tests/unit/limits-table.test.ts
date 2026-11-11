import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_PLANS, LIMIT_ROWS, PLAN_CODES, annualSaving, daysUntil, formatLimit, limitCell, money, trialReminder, usageMeters, withVat, type RtAccount } from "../../src/lib/billing.ts";
import { scrub } from "../../src/lib/sentry.ts";

const grid = (plans = DEFAULT_PLANS) => Object.fromEntries(LIMIT_ROWS.map((r) => [r.label, PLAN_CODES.map((c) => limitCell(r, c, plans))]));

test("the limits table is the contract's, row by row", () => {
  const g = grid();
  assert.deepEqual(g["Users"], ["1", "3", "10"]);
  assert.deepEqual(g["AI-read documents"], ["50", "300", "1,500"]);
  assert.deepEqual(g["Ask questions"], ["100", "500", "3,000"]);
  assert.deepEqual(g["Live bank feeds"], ["1", "3", "Unlimited"]);
  assert.deepEqual(g["Sales invoices and quotes"], ["20", "Unlimited", "Unlimited"]);
  assert.deepEqual(g["Marketplace connections"], ["—", "1", "Unlimited"]);
  assert.deepEqual(g["Payroll (employees)"], ["—", "Up to 3", "Up to 20"]);
  assert.deepEqual(g["Autopilot rules"], ["5", "Unlimited", "Unlimited"]);
  assert.deepEqual(g["Multi-currency, projects and job costing"], ["—", "—", "Included"]);
  assert.deepEqual(g["Support"], ["Email", "Email", "Priority email"]);
  assert.deepEqual(g["VAT returns"], ["Included", "Included", "Included"]);
});

test("live limits from GET /plans win over the table; missing keys fall back", () => {
  const live = DEFAULT_PLANS.map((p) => (p.code === "starter" ? { ...p, limits: { docs: 75 } } : p));
  const g = grid(live);
  assert.equal(g["AI-read documents"][0], "75");
  assert.equal(g["Users"][0], "1");
});

test("cells: unlimited, none, included, text", () => {
  assert.equal(formatLimit(null), "Unlimited");
  assert.equal(formatLimit(0), "—");
  assert.equal(formatLimit(true), "Included");
  assert.equal(formatLimit("Email"), "Email");
});

test("prices: ex VAT, with VAT and the annual saving (2 months free)", () => {
  assert.deepEqual(DEFAULT_PLANS.map((p) => money(p.price_month_pence)), ["£10", "£20", "£50"]);
  assert.deepEqual(DEFAULT_PLANS.map((p) => money(withVat(p.price_month_pence))), ["£12", "£24", "£60"]);
  assert.deepEqual(DEFAULT_PLANS.map((p) => money(annualSaving(p))), ["£20", "£40", "£100"]);
  assert.equal(money(300), "£3");
  assert.equal(money(833), "£8.33");
});

const acct = (over: Partial<RtAccount> = {}): RtAccount => ({
  id: "1", email: "a@b.c", plan_code: "starter", status: "trialing", trial_ends_at: "2026-12-01T00:00:00Z", comp_until: null, billing_interval: null,
  usage: { docs: 45, ask: 10, invoices: 20, bank_feeds: 1, users: 1, marketplaces: 0, topup_docs_remaining: 100 },
  limits: DEFAULT_PLANS[0].limits, own_ai: false, ...over,
});

test("trial reminder: only while trialing and in the last 14 days", () => {
  const now = new Date("2026-11-20T12:00:00Z");
  assert.equal(daysUntil("2026-12-01T00:00:00Z", now), 11);
  assert.deepEqual(trialReminder(acct(), now), { days: 11 });
  assert.equal(trialReminder(acct({ trial_ends_at: "2027-01-30T00:00:00Z" }), now), null);
  assert.equal(trialReminder(acct({ status: "active" }), now), null);
});

test("usage meters: against the limits, near and full, unlimited, own AI", () => {
  const m = Object.fromEntries(usageMeters(acct()).map((x) => [x.key, x]));
  assert.equal(m.docs.limit, 50);
  assert.equal(m.docs.state, "near");
  assert.equal(m.docs.extra, "100 top-up documents left");
  assert.equal(m.invoices.state, "full");
  assert.equal(m.marketplaces, undefined); // not on this plan and unused
  const own = Object.fromEntries(usageMeters(acct({ own_ai: true })).map((x) => [x.key, x]));
  assert.equal(own.docs.limit, null);
});

test("the error scrubber removes amounts, emails, VAT numbers and tokens", () => {
  const out = scrub({ message: "Paid £1,240.50 to a@b.co.uk VAT GB123456789 token eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.abcdefghijkl", nested: ["£5"] });
  assert.equal(out.message, "Paid [amount] to [email] VAT [vat] token [token]");
  assert.deepEqual(out.nested, ["[amount]"]);
});
