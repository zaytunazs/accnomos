/** PayPal disputes (services/runtime/app/routes_paypal_disputes.py). Nothing reaches PayPal without `confirm: true`,
 *  which the Disputes panel sends only when the owner taps "Send to PayPal". */
import type { AccountInfo } from "@azure/msal-browser";
import { RUNTIME_URL } from "./ai-config";
import { runtimeHeaders } from "./runtime";

export interface RtJournalLine {
  account: string;
  debit_pence: number;
  credit_pence: number;
  vat_code: string | null;
}

export interface RtEvidenceProposal {
  dispute_id: string;
  invoice: string;
  evidence_type: string;
  notes: string; // the response PayPal gets, checked by code against the books
  model: string;
  fallback_reason: string | null; // why code wrote the response instead of the model
  facts: Record<string, unknown>;
  pdf_path: string;
  pdf_sha256: string;
  built_at: string;
  built_by: string;
  status: "proposed" | "sent";
  sent_at: string | null;
  sent_by: string | null;
  demo: boolean; // a demo's sample: "sent" without calling PayPal
  reversal_payment: string | null;
  reversal_at: string | null;
}

export interface RtDisputeReversal {
  payment_record: string;
  amount_pence: number;
  refunded_pence: number | null;
  can_post: boolean;
  reason: string | null;
  journal: RtJournalLine[];
}

export interface RtDispute {
  dispute_id: string;
  sample: boolean;
  reason: string;
  reason_text: string;
  status: string;
  state: string | null;
  stage: string | null;
  amount_pence: number | null;
  respond_by: string | null;
  opened: string | null;
  invoice: string | null; // null: not a payment Accnomos knows about
  customer: string | null;
  transaction_id: string | null;
  can_send_evidence: boolean;
  outcome: string | null;
  lost: boolean;
  proposal: RtEvidenceProposal | null;
  reversal: RtDisputeReversal | null;
}

export interface RtDisputeList {
  connected: boolean;
  disputes: RtDispute[];
  problem: string | null;
}

const BASE = "/payments/online/paypal/disputes";

async function request(a: AccountInfo, path: string, init: RequestInit = {}): Promise<Response> {
  const json = typeof init.body === "string";
  const headers = { ...(await runtimeHeaders(a)), ...(json ? { "Content-Type": "application/json" } : {}) };
  const res = await fetch(`${RUNTIME_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `${init.method ?? "GET"} ${path} failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res;
}

const id = (d: string) => encodeURIComponent(d);

export const disputes = {
  list: async (a: AccountInfo) => (await (await request(a, BASE)).json()) as RtDisputeList,
  /** Drafting sends nothing: the response and the PDF are for the owner to preview. */
  build: async (a: AccountInfo, d: string) =>
    (await (await request(a, `${BASE}/${id(d)}/evidence`, { method: "POST" })).json()) as RtEvidenceProposal,
  pdf: async (a: AccountInfo, d: string) => (await request(a, `${BASE}/${id(d)}/evidence.pdf`)).blob(),
  /** The owner's yes. */
  send: async (a: AccountInfo, d: string) =>
    (await (
      await request(a, `${BASE}/${id(d)}/evidence/send`, { method: "POST", body: JSON.stringify({ confirm: true }) })
    ).json()) as RtEvidenceProposal,
  reverse: async (a: AccountInfo, d: string) =>
    (await (
      await request(a, `${BASE}/${id(d)}/reversal`, { method: "POST", body: JSON.stringify({ confirm: true }) })
    ).json()) as RtDisputeReversal,
};
