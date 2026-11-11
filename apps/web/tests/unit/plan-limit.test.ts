import assert from "node:assert/strict";
import { test } from "node:test";
import { handlePlanLimit, parsePlanLimit, planLimitMessage, topUpHelps, type PlanLimitInfo } from "../../src/lib/plan-limit.ts";

test("a 402 with code plan_limit is recognised, top-level or under detail", () => {
  const a = parsePlanLimit(402, JSON.stringify({ code: "plan_limit", limit: "docs", plan_code: "starter", message: "50 of 50" }));
  assert.deepEqual(a, { code: "plan_limit", message: "50 of 50", limit_key: "docs", plan_code: "starter" });
  const b = parsePlanLimit(402, JSON.stringify({ detail: { code: "plan_limit", limit_key: "ask" } }));
  assert.equal(b?.limit_key, "ask");
  assert.equal(b?.plan_code, null);
});

test("anything else is not a plan limit", () => {
  assert.equal(parsePlanLimit(500, JSON.stringify({ code: "plan_limit" })), null);
  assert.equal(parsePlanLimit(402, JSON.stringify({ code: "payment_required" })), null);
  assert.equal(parsePlanLimit(402, "not json"), null);
  assert.equal(parsePlanLimit(402, "null"), null);
});

test("handlePlanLimit tells the dialog once for a limit and never for other errors", () => {
  const seen: PlanLimitInfo[] = [];
  assert.ok(handlePlanLimit(402, JSON.stringify({ code: "plan_limit", limit: "docs" }), (i) => seen.push(i)));
  assert.equal(handlePlanLimit(404, "{}", (i) => seen.push(i)), null);
  assert.equal(handlePlanLimit(402, "{}", (i) => seen.push(i)), null);
  assert.equal(seen.length, 1);
});

test("the message is friendly and says nothing is locked; only documents can be topped up", () => {
  const docs: PlanLimitInfo = { code: "plan_limit", message: null, limit_key: "docs", plan_code: null };
  assert.match(planLimitMessage(docs), /AI-read documents/);
  assert.match(planLimitMessage(docs), /approve, edit and export/);
  assert.equal(topUpHelps(docs), true);
  assert.equal(topUpHelps({ ...docs, limit_key: "bank_feeds" }), false);
  assert.match(planLimitMessage({ ...docs, limit_key: null }), /a limit on your plan/);
});
