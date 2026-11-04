import type { Page } from "@playwright/test";
import { RELAY_URL, WEB_URL } from "./env.mjs";

/**
 * A stand-in for the relay answering a demo as HMRC's sandbox does (the shapes recorded in docs/HMRC_SANDBOX_DEMO.md
 * from a live run): a fresh test organisation, the sign-in round trip (HMRC's page itself is skipped: /hmrc/authorize
 * points straight back at /vat with a code), the test user's obligations (HMRC's 2017 test data) and a receipt.
 * Nothing leaves 127.0.0.1. `calls` lists the paths asked for, in order, with the submitted bodies.
 */
export const SANDBOX_USER = { userId: "893247528116", password: "e2e-sandbox-pass", vrn: "510266389" };
export const SANDBOX_RECEIPT = {
  processingDate: "2026-11-04T05:53:37.493Z",
  formBundleNumber: "409715423288",
  paymentIndicator: "DD",
  chargeRefNumber: "mzeEeAVbErCFvD3H",
};

export async function routeSandboxRelay(page: Page, opts: { testUser?: "ok" | "unconfigured" } = {}) {
  const calls: { path: string; body: unknown }[] = [];
  await page.route(`${RELAY_URL}/**`, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    let body: unknown = null;
    try {
      body = req.postDataJSON();
    } catch {
      /* no body */
    }
    calls.push({ path, body });
    const headers = { "Access-Control-Allow-Origin": "*" };
    const json = (status: number, b: unknown) => route.fulfill({ status, json: b, headers });
    const envelope = (hmrc: unknown) => ({
      hmrc,
      sent_headers: { "Gov-Client-Connection-Method": "WEB_APP_VIA_SERVER" },
      fraud_headers_missing: [],
      correlation_id: "ad2e5631-9d8e-481d-aa35-85fc471e7e07",
      receipt_id: null,
      receipt_timestamp: null,
    });
    if (path === "/hmrc/test-user") {
      if (opts.testUser === "unconfigured") return json(503, { detail: "Relay is not configured with HMRC credentials" });
      return json(201, { ...SANDBOX_USER, userFullName: "Ida Test", organisationDetails: { name: "Company ABC Ltd" } });
    }
    if (path === "/hmrc/authorize") return json(200, { url: `${WEB_URL}/vat#code=e2e-code&state=e2e-state`, state: "e2e-state" });
    if (path === "/hmrc/exchange") return json(200, { access_token: "hmrc-sandbox", refresh_token: "r", expires_in: 14400, scope: "read:vat write:vat" });
    if (path === `/vat/${SANDBOX_USER.vrn}/obligations`)
      return json(
        200,
        envelope({
          obligations: [
            { periodKey: "18A1", start: "2017-01-01", end: "2017-03-31", due: "2017-05-07", status: "F", received: "2017-05-06" },
            { periodKey: "18A2", start: "2017-04-01", end: "2017-06-30", due: "2017-08-07", status: "O" },
          ],
        }),
      );
    if (path === `/vat/${SANDBOX_USER.vrn}/returns`) return json(201, envelope(SANDBOX_RECEIPT));
    return json(404, { detail: "not stubbed" });
  });
  return calls;
}
