import assert from "node:assert/strict";
import { test } from "node:test";
import { cleanProps, createTracker, type TrackEvent } from "../../src/lib/analytics-core.ts";

function make(opts: { optedOut?: () => boolean; maxBatch?: number } = {}) {
  const sent: TrackEvent[][] = [];
  const timers: (() => void)[] = [];
  const t = createTracker({
    send: async (e) => (sent.push(e), true),
    optedOut: opts.optedOut ?? (() => false),
    version: "9.9.9",
    maxBatch: opts.maxBatch,
    setTimer: (fn) => timers.push(fn),
    clearTimer: () => undefined,
  });
  return { t, sent, timers };
}

test("events are batched: one send after the timer, with the app and version", async () => {
  const { t, sent, timers } = make();
  t.track("page_view", { page: "/review" });
  t.track("scan_started");
  assert.equal(sent.length, 0);
  assert.equal(timers.length, 1);
  await t.flush();
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].map((e) => e.name), ["page_view", "scan_started"]);
  assert.equal(sent[0][0].app, "web");
  assert.equal(sent[0][0].version, "9.9.9");
});

test("a full batch is sent at once", async () => {
  const { t, sent } = make({ maxBatch: 3 });
  for (let i = 0; i < 3; i++) t.track(`e${i}`);
  await Promise.resolve();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].length, 3);
});

test("opted out: nothing is queued or sent, and what waited is dropped", async () => {
  let out = false;
  const { t, sent } = make({ optedOut: () => out });
  t.track("before");
  out = true;
  t.track("after");
  await t.flush();
  assert.equal(sent.length, 0);
  assert.equal(t.pending(), 0);
});

test("discard clears the queue", () => {
  const { t } = make();
  t.track("x");
  t.discard();
  assert.equal(t.pending(), 0);
});

test("properties keep counts and short labels, never money, people or files", () => {
  assert.deepEqual(cleanProps({ page: "/vat", count: 3, ok: true, amount: 12.5, supplier_name: "Novex", email: "a@b.c", note: "a@b.com", long: "x".repeat(60), file: "r.pdf", nested: { a: 1 } }), { page: "/vat", count: 3, ok: true });
});

test("a failing send never throws", async () => {
  const t = createTracker({ send: async () => { throw new Error("offline"); }, optedOut: () => false, version: "1", setTimer: () => 0, clearTimer: () => undefined });
  t.track("x");
  await t.flush();
});
