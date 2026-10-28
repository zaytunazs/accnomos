"use client";

import { RELAY_URL } from "./ai-config";

/**
 * HMRC MTD VAT (sandbox) through the stateless relay (services/hmrc-relay). OAuth is PKCE: only this
 * browser holds the verifier, and the tokens live only in sessionStorage (gone when the tab closes).
 * The relay holds the client secret and adds the fraud-prevention headers from the facts we send.
 */

/**
 * Two HMRC sessions side by side: VAT (`read:vat write:vat`, on /vat) and Income Tax (`read:self-assessment
 * write:self-assessment`, on /self-employment). Each keeps its own tokens, so connecting one never drops the other.
 */
export type HmrcSession = "vat" | "itsa" | "property";
// The UK property page (/property) uses the same Income Tax scopes, so it shares the Income Tax tokens.
const TOKENS_KEYS: Record<HmrcSession, string> = { vat: "accnomos.hmrc", itsa: "accnomos.hmrc.itsa", property: "accnomos.hmrc.itsa" };
// {verifier, state} between /hmrc/authorize and the redirect back
const PENDING_KEYS: Record<HmrcSession, string> = {
  vat: "accnomos.hmrc.pending",
  itsa: "accnomos.hmrc.itsa.pending",
  property: "accnomos.hmrc.property.pending",
};
const SESSION_SETUP: Record<HmrcSession, { path: string; scope: string }> = {
  vat: { path: "/vat", scope: "read:vat write:vat" },
  itsa: { path: "/self-employment", scope: "read:self-assessment write:self-assessment" },
  property: { path: "/property", scope: "read:self-assessment write:self-assessment" },
};
const DEVICE_KEY = "accnomos.device_id";
export const VRN_KEY = "accnomos.business.vrn";
const APP_VERSION = "0.1.0";

export interface HmrcTokens {
  access_token: string;
  refresh_token: string;
  expires_at: number; // epoch ms
  scope?: string;
  token_type?: string;
}

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  scope?: string;
  token_type?: string;
}

/** Relay `ClientFacts` (services/hmrc-relay/relay/fraud_headers.py). Absent = genuinely unavailable. */
export interface ClientFacts {
  device_id?: string;
  multi_factor: [];
  screens?: { width: number; height: number; scaling_factor: number; colour_depth: number }[];
  timezone?: string;
  user_ids?: Record<string, string>;
  window_size?: { width: number; height: number };
  browser_js_user_agent?: string;
  vendor_versions: Record<string, string>;
}

/** Every VAT endpoint answers with this envelope. */
export interface RelayResult<T> {
  hmrc: T;
  sent_headers: Record<string, string>;
  fraud_headers_missing: string[];
  correlation_id: string | null;
  receipt_id: string | null;
  receipt_timestamp: string | null;
}

export interface Obligation {
  periodKey: string;
  start: string;
  end: string;
  due: string;
  status: "O" | "F";
  received?: string;
}

/** The 11 fields HMRC requires (POST /organisations/vat/{vrn}/returns). */
export interface VatReturnBody {
  periodKey: string;
  vatDueSales: number;
  vatDueAcquisitions: number;
  totalVatDue: number;
  vatReclaimedCurrPeriod: number;
  netVatDue: number;
  totalValueSalesExVAT: number;
  totalValuePurchasesExVAT: number;
  totalValueGoodsSuppliedExVAT: number;
  totalAcquisitionsExVAT: number;
  finalised: boolean;
}

export interface SubmitReceipt {
  processingDate: string;
  formBundleNumber: string;
  paymentIndicator?: string;
  chargeRefNumber?: string;
}

export class RelayError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Raised when the HMRC session has gone (no tokens, or refresh failed): the user must connect again. */
export class HmrcAuthError extends Error {}

// --- small helpers ---------------------------------------------------------------------------------------

const b64url = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const sha256 = async (s: string) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
export const sha256Hex = async (s: string) => Array.from(await sha256(s), (b) => b.toString(16).padStart(2, "0")).join("");

function store(kind: "local" | "session"): Storage | null {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null; // storage unavailable (private mode)
  }
}

function readJson<T>(s: Storage | null, key: string): T | null {
  try {
    const raw = s?.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/** Pull a readable message out of relay / HMRC / FastAPI validation errors. */
function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const b = body as { message?: string; detail?: unknown; errors?: { message?: string }[] };
    if (Array.isArray(b.detail)) return b.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
    if (typeof b.detail === "string") return b.detail;
    if (b.message) return [b.message, ...(b.errors ?? []).map((e) => e.message).filter(Boolean)].join(" · ");
  }
  return fallback;
}

export async function relay<T>(path: string, init: RequestInit & { token?: string } = {}): Promise<T> {
  const { token, ...rest } = init;
  const headers: Record<string, string> = {};
  if (rest.body) headers["Content-Type"] = "application/json";
  if (token) headers["X-HMRC-Access-Token"] = token;
  let res: Response;
  try {
    res = await fetch(`${RELAY_URL}${path}`, { ...rest, headers });
  } catch {
    throw new RelayError(`Couldn't reach the HMRC relay at ${RELAY_URL}.`, 0);
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* not JSON */
  }
  if (!res.ok) throw new RelayError(errorMessage(body, `relay ${path} -> ${res.status}: ${text.slice(0, 200)}`), res.status);
  return body as T;
}

// --- tokens ------------------------------------------------------------------------------------------------

export const loadTokens = (kind: HmrcSession = "vat") => readJson<HmrcTokens>(store("session"), TOKENS_KEYS[kind]);

function saveTokens(t: TokenResponse, kind: HmrcSession = "vat"): HmrcTokens {
  const tokens: HmrcTokens = {
    access_token: t.access_token,
    refresh_token: t.refresh_token,
    expires_at: Date.now() + t.expires_in * 1000,
    scope: t.scope,
    token_type: t.token_type,
  };
  store("session")?.setItem(TOKENS_KEYS[kind], JSON.stringify(tokens));
  return tokens;
}

export function disconnect(kind: HmrcSession = "vat"): void {
  store("session")?.removeItem(TOKENS_KEYS[kind]);
  store("session")?.removeItem(PENDING_KEYS[kind]);
}

/** A valid access token, refreshed through the relay a minute before it expires. */
export async function accessToken(kind: HmrcSession = "vat"): Promise<string> {
  const t = loadTokens(kind);
  if (!t) throw new HmrcAuthError("Not connected to HMRC.");
  if (Date.now() < t.expires_at - 60_000) return t.access_token;
  try {
    return saveTokens(await hmrc.refresh(t.refresh_token), kind).access_token;
  } catch (e) {
    disconnect(kind);
    throw new HmrcAuthError(`Your HMRC session has ended (${(e as Error).message}). Connect again.`);
  }
}

// --- OAuth (PKCE) ------------------------------------------------------------------------------------------

/** Start the HMRC consent flow; the relay callback sends the browser back to `/vat#code=…&state=…`
 *  (or `/self-employment#…` for the Income Tax session, which asks for the self-assessment scopes). */
export async function startConnect(kind: HmrcSession = "vat"): Promise<void> {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(48))); // 64 chars
  const challenge = b64url(await sha256(verifier));
  const { path, scope } = SESSION_SETUP[kind];
  const redirectTo = `${window.location.origin}${path}`;
  const q = new URLSearchParams({ redirect_to: redirectTo, code_challenge: challenge, ...(kind === "vat" ? {} : { scope }) });
  const { url, state } = await relay<{ url: string; state: string }>(`/hmrc/authorize?${q}`);
  store("session")?.setItem(PENDING_KEYS[kind], JSON.stringify({ verifier, state }));
  window.location.assign(url);
}

export type OAuthCallback = { code: string; state: string } | { error: string; description: string };

/**
 * Read the OAuth result from the URL fragment and remove it straight away (synchronously, before any
 * await) so it isn't bookmarked, re-used on reload, or seen by anything else that parses the hash.
 */
export function takeCallback(): OAuthCallback | null {
  const p = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const code = p.get("code");
  const error = p.get("error");
  if (!code && !error) return null;
  if (!p.get("state")) return null;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  if (error) return { error, description: p.get("error_description") ?? "" };
  return { code: code!, state: p.get("state")! };
}

/** Exchange the code for tokens with our verifier. The pending entry is single-use. */
export async function finishConnect(cb: { code: string; state: string }, kind: HmrcSession = "vat"): Promise<HmrcTokens> {
  const pending = readJson<{ verifier: string; state: string }>(store("session"), PENDING_KEYS[kind]);
  store("session")?.removeItem(PENDING_KEYS[kind]);
  if (!pending) throw new Error("This HMRC sign-in wasn't started in this tab. Please connect again.");
  if (pending.state !== cb.state) throw new Error("HMRC sign-in state didn't match. Please connect again.");
  return saveTokens(
    await relay<TokenResponse>("/hmrc/exchange", {
      method: "POST",
      body: JSON.stringify({ code: cb.code, state: cb.state, code_verifier: pending.verifier }),
    }),
    kind,
  );
}

// --- fraud-prevention facts ----------------------------------------------------------------------------------

function deviceId(): string | undefined {
  const s = store("local");
  if (!s) return undefined; // can't persist one, so don't invent a fresh id per call
  let id = s.getItem(DEVICE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    s.setItem(DEVICE_KEY, id);
  }
  return id;
}

function utcOffset(): string {
  const mins = -new Date().getTimezoneOffset();
  const abs = Math.abs(mins);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `UTC${mins >= 0 ? "+" : "-"}${hh}:${mm}`;
}

/** Facts for the Gov-Client-* headers, read fresh for each call (window size can change). */
export async function clientFacts(homeAccountId: string): Promise<ClientFacts> {
  const facts: ClientFacts = { multi_factor: [], vendor_versions: { "accnomos-web": APP_VERSION } };
  const id = deviceId();
  if (id) facts.device_id = id;
  if (screen?.width && screen?.height && screen.colorDepth) {
    facts.screens = [{ width: screen.width, height: screen.height, scaling_factor: window.devicePixelRatio || 1, colour_depth: screen.colorDepth }];
  }
  facts.timezone = utcOffset();
  if (homeAccountId) facts.user_ids = { accnomos: await sha256Hex(homeAccountId) };
  if (window.innerWidth && window.innerHeight) facts.window_size = { width: window.innerWidth, height: window.innerHeight };
  if (navigator.userAgent) facts.browser_js_user_agent = navigator.userAgent;
  return facts;
}

// --- VAT (MTD) -------------------------------------------------------------------------------------------------

async function vat<T>(path: string, facts: ClientFacts, extra: Record<string, unknown>, scenario?: string): Promise<RelayResult<T>> {
  const body = { client_facts: facts, method: "WEB_APP_VIA_SERVER", ...(scenario?.trim() ? { gov_test_scenario: scenario.trim() } : {}), ...extra };
  return relay<RelayResult<T>>(path, { method: "POST", body: JSON.stringify(body), token: await accessToken() });
}

export const hmrc = {
  obligations: (vrn: string, facts: ClientFacts, range: { from: string; to: string; status?: "O" | "F" }, scenario?: string) =>
    vat<{ obligations: Obligation[] }>(`/vat/${vrn}/obligations`, facts, range, scenario),
  submit: (vrn: string, facts: ClientFacts, ret: VatReturnBody, scenario?: string) =>
    vat<SubmitReceipt>(`/vat/${vrn}/returns`, facts, { return: ret }, scenario),
  view: (vrn: string, facts: ClientFacts, periodKey: string, scenario?: string) =>
    vat<VatReturnBody>(`/vat/${vrn}/returns/${encodeURIComponent(periodKey)}/view`, facts, {}, scenario),
  refresh: (refreshToken: string) =>
    relay<TokenResponse>("/hmrc/refresh", { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) }),
};

/**
 * The runtime's `hmrc_body` (computed by code from the ledger) under the obligation's period key, finalised.
 * Boxes 1–5 rounded to pence, 6–9 whole pounds, box 5 as an absolute value, so the relay's checks hold.
 */
export function toReturnBody(hmrcBody: Record<string, unknown>, periodKey: string): VatReturnBody {
  const p = (k: string) => Math.round(Number(hmrcBody[k] ?? 0) * 100) / 100;
  const w = (k: string) => Math.trunc(Number(hmrcBody[k] ?? 0));
  return {
    periodKey,
    vatDueSales: p("vatDueSales"),
    vatDueAcquisitions: p("vatDueAcquisitions"),
    totalVatDue: p("totalVatDue"),
    vatReclaimedCurrPeriod: p("vatReclaimedCurrPeriod"),
    netVatDue: Math.abs(p("netVatDue")),
    totalValueSalesExVAT: w("totalValueSalesExVAT"),
    totalValuePurchasesExVAT: w("totalValuePurchasesExVAT"),
    totalValueGoodsSuppliedExVAT: w("totalValueGoodsSuppliedExVAT"),
    totalAcquisitionsExVAT: w("totalAcquisitionsExVAT"),
    finalised: true,
  };
}

/** VRN to prefill: the one used last, else the business's VAT number if it's a plain GB 9-digit one. */
export function savedVrn(): string {
  const s = store("local");
  const direct = s?.getItem(VRN_KEY);
  if (direct) return direct;
  const biz = readJson<{ vatNumber?: string }>(s, "accnomos.business");
  const digits = (biz?.vatNumber ?? "").replace(/\s+/g, "").toUpperCase().replace(/^GB/, "");
  return /^\d{9}$/.test(digits) ? digits : "";
}

export function rememberVrn(vrn: string): void {
  store("local")?.setItem(VRN_KEY, vrn);
}
