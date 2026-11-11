"use client";

/**
 * Optional error reporting for the web app, only when NEXT_PUBLIC_SENTRY_DSN is set at build time (an EU-region
 * project). Unset, the branch is folded away at build time and the SDK is in no bundle. Set, it loads on first use,
 * with personal data off, no cookies, headers, request bodies or query strings, and a scrubber over everything that
 * leaves (amounts, emails, VAT numbers, tokens). The CSP must allow the ingest host: docs/billing/ADMIN_UI_NOTES.md.
 */

const PATTERNS: [RegExp, string][] = [
  [/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, "[email]"],
  [/\bGB\s?\d{3}\s?\d{4}\s?\d{2}(?:\s?\d{3})?\b/gi, "[vat]"],
  [/\b(?:eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}|Bearer\s+[\w.~+/-]{12,}|[A-Za-z0-9_-]{32,})\b/g, "[token]"],
  [/[£$€]\s?\d[\d,]*(?:\.\d{1,2})?/g, "[amount]"],
];

/** Replaces money, emails, VAT numbers and token-like strings in any string inside `value`. */
export function scrub<T>(value: T, depth = 0): T {
  if (typeof value === "string") return PATTERNS.reduce<string>((s, [re, to]) => s.replace(re, to), value) as T;
  if (depth > 8 || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((v) => scrub(v, depth + 1)) as T;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) out[k] = scrub(v, depth + 1);
  return out as T;
}

export function initSentry(): void {
  // Written out in the condition (not read into a variable first) so an unset DSN folds the whole branch away.
  if (!process.env.NEXT_PUBLIC_SENTRY_DSN || typeof window === "undefined") return;
  void import("@sentry/browser").then((Sentry) => {
    Sentry.init({
      dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
      // This SDK version replaced sendDefaultPii with dataCollection: nothing personal, no cookies, headers, bodies or query strings.
      dataCollection: { userInfo: false, cookies: false, httpHeaders: false, httpBodies: [], urlQueryParams: false },
      tracesSampleRate: 0,
      defaultIntegrations: false,
      integrations: [Sentry.globalHandlersIntegration(), Sentry.dedupeIntegration()],
      beforeSend(event) {
        delete event.request;
        delete event.user;
        delete event.server_name;
        return scrub(event);
      },
      beforeBreadcrumb: () => null,
    });
  });
}
