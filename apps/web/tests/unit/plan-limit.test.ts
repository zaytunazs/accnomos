import assert from "node:assert/strict";
import { test } from "node:test";
import { handlePlanLimit, parseBillingRefusal, parsePlanLimit, planLimitMessage, refusalTitle, topUpHelps, type BillingRefusal } from "../../src/lib/plan-limit.ts";

// The runtime's bodies (services/runtime/app/billing/service.py PlanLimit.body / ReadOnly.body)
const LIMIT = { code: "plan_limit", counter: "docs", limit: 50, used: 50, upgrade_url: "https://accnomos.com/settings/billing", detail: "You've used 50 of 50 AI-read documents this month." };
const READ_ONLY = { code: "read_only", status: "trial_ended", upgrade_url: "https://accnomos.com/settings/billing", detail: "Your free trial has ended." };

test("a 402 plan_limit is read with its counter, limit and use, top level or under detail", () => {
  assert.deepEqual(parsePlanLimit(402, JSON.stringify(LIMIT)), LIMIT);
  const b = parseBillingRefusal(402, JSON.stringify({ detail: { ...LIMIT, counter: "ask" } }));
  assert.equal(b?.code === "plan_limit" && b.counter, "ask");
});

test("a 402 read_only is read too, and is not a plan limit", () => {
  assert.deepEqual(parseBillingRefusal(402, JSON.stringify(READ_ONLY)), READ_ONLY);
  assert.equal(parsePlanLimit(402, JSON.stringify(READ_ONLY)), null);
});

test("anything else is not a billing refusal", () => {
  assert.equal(parseBillingRefusal(500, JSON.stringify(LIMIT)), null);
  assert.equal(parseBillingRefusal(402, JSON.stringify({ code: "payment_required" })), null);
  assert.equal(parseBillingRefusal(402, "not json"), null);
  assert.equal(parseBillingRefusal(402, "null"), null);
  assert.equal(parseBillingRefusal(402, "[]"), null);
});

test("handlePlanLimit tells the dialog once for a refusal and never for other errors", () => {
  const seen: BillingRefusal[] = [];
  handlePlanLimit(402, JSON.stringify(LIMIT), (i) => seen.push(i));
  handlePlanLimit(402, JSON.stringify(READ_ONLY), (i) => seen.push(i));
  handlePlanLimit(500, JSON.stringify(LIMIT), (i) => seen.push(i));
  handlePlanLimit(402, JSON.stringify({ detail: "Payment required" }), (i) => seen.push(i));
  assert.deepEqual(seen.map((s) => s.code), ["plan_limit", "read_only"]);
});

test("the sentences are friendly, name the limit and say nothing is locked", () => {
  const docs = parsePlanLimit(402, JSON.stringify(LIMIT))!;
  assert.match(planLimitMessage(docs), /all 50 of this month's AI-read documents/);
  assert.match(planLimitMessage(docs), /approve, edit and export/);
  assert.match(planLimitMessage({ ...docs, counter: "marketplaces", limit: 0, used: 0 }), /does not include marketplace connections/);
  assert.match(planLimitMessage({ ...docs, counter: "bank_feeds", limit: 3, used: 3 }), /allows 3 live bank feeds/);
  assert.match(planLimitMessage({ ...docs, counter: null }), /a limit on your plan/);
  const ro = parseBillingRefusal(402, JSON.stringify(READ_ONLY))!;
  assert.equal(refusalTitle(ro), "Your free trial has ended");
  assert.match(planLimitMessage(ro), /read-only.*view and export/);
  assert.equal(refusalTitle({ ...ro, code: "read_only", status: "cancelled" }), "Your plan has been cancelled");
});

test("a top-up helps documents only", () => {
  const docs = parsePlanLimit(402, JSON.stringify(LIMIT))!;
  assert.equal(topUpHelps(docs), true);
  assert.equal(topUpHelps({ ...docs, counter: "ask" }), false);
  assert.equal(topUpHelps(parseBillingRefusal(402, JSON.stringify(READ_ONLY))!), false);
});
