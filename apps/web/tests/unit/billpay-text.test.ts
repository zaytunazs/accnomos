/** The honest copy for upcoming PayPal payments (src/lib/billpay-text.ts). */
import assert from "node:assert/strict";
import { test } from "node:test";
import { calendarName, paysLine, UPCOMING_STATUS } from "../../src/lib/billpay-text.ts";

test("paysLine says when Accnomos pays and that PayPal cannot hold a payment", () => {
  assert.equal(
    paysLine("2026-12-01"),
    "Accnomos pays this the next time it is open on or after 1 Dec 2026 — PayPal cannot hold a payment for a future date.",
  );
  assert.match(paysLine("2027-03-31"), /31 Mar 2027/);
});

test("calendarName follows the account the user signed in with", () => {
  assert.equal(calendarName("google"), "Google Calendar");
  assert.equal(calendarName("personal"), "Outlook calendar");
  assert.equal(calendarName("work"), "Outlook calendar");
  assert.equal(calendarName("other"), "your calendar");
});

test("every status has words and none promises what is not built", () => {
  for (const words of Object.values(UPCOMING_STATUS)) {
    assert.ok(words.length > 0);
    assert.doesNotMatch(words, /coming soon|beta|launch/i);
  }
});
