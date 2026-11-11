"use client";

import { useEffect, useState } from "react";
import { RELAY_URL } from "./ai-config";
import { isDemo } from "./demo";

/**
 * Which HMRC environment the relay files to, and what can be filed from Accnomos there (relay GET /hmrc/status,
 * services/hmrc-relay/relay/routes.py). HMRC_ENV on the relay decides it: sandbox by default, production once the
 * owner has HMRC's production credentials for VAT. Income Tax is never filed live from Accnomos (HMRC is not issuing
 * production credentials for new 2026-27 quarterly-update products), so its page offers the "File it yourself" files.
 * The demo always uses HMRC's sandbox, whatever the relay says.
 */

/** The one sentence shown wherever filing to HMRC from Accnomos is off (the relay and the runtime use it too). */
export const PLANNED = "Filing to HMRC from Accnomos is planned.";

export interface HmrcStatus {
  environment: "sandbox" | "production";
  /** VAT returns go to HMRC's live service from this app. */
  vatLive: boolean;
  /** The VAT Submit flow is there at all (to the sandbox, or live). */
  vatSubmit: boolean;
  /** Always false: Income Tax updates are never filed live from Accnomos. */
  itsaLive: false;
  /** The Income Tax sandbox practice flow is there (off in production mode). */
  itsaSubmit: boolean;
  /** False when the relay couldn't be asked: sandbox is assumed, as before this switch existed. */
  known: boolean;
}

interface RelayStatus {
  environment?: string;
  configured?: boolean;
  vat?: { live_filing?: boolean; submit_available?: boolean };
  itsa?: { submit_available?: boolean };
}

const SANDBOX_ASSUMED: HmrcStatus = { environment: "sandbox", vatLive: false, vatSubmit: true, itsaLive: false, itsaSubmit: true, known: false };

let cached: Promise<HmrcStatus> | null = null;

export function readStatus(j: RelayStatus | null, demo: boolean): HmrcStatus {
  if (!j || (j.environment !== "sandbox" && j.environment !== "production")) return SANDBOX_ASSUMED;
  if (demo) return { ...SANDBOX_ASSUMED, known: true }; // the demo files to HMRC's sandbox with its own test user
  const production = j.environment === "production";
  return {
    environment: j.environment,
    vatLive: production && j.vat?.live_filing === true,
    vatSubmit: j.vat?.submit_available !== false,
    itsaLive: false,
    itsaSubmit: !production && j.itsa?.submit_available !== false,
    known: true,
  };
}

/** Asked once per page load; a relay that can't be reached means the sandbox, as before. */
export function fetchHmrcStatus(): Promise<HmrcStatus> {
  cached ??= fetch(`${RELAY_URL}/hmrc/status`)
    .then((r) => (r.ok ? (r.json() as Promise<RelayStatus>) : null))
    .catch(() => null)
    .then((j) => readStatus(j, isDemo()));
  return cached;
}

export function useHmrcStatus(): HmrcStatus | null {
  const [status, setStatus] = useState<HmrcStatus | null>(null);
  useEffect(() => {
    let stale = false;
    fetchHmrcStatus().then((s) => !stale && setStatus(s));
    return () => {
      stale = true;
    };
  }, []);
  return status;
}
