import { RUNTIME_URL } from "@/lib/ai-config";

/** Must match CONSENT_TEXT in services/runtime/app/early_access.py: the runtime stores it with each sign-up and
 * refuses any other wording. */
export const CONSENT_TEXT = "Email me once Accnomos launches, with my 3 months free. I can unsubscribe any time.";
export const SUCCESS_TEXT = "You're on the list — we'll email you once at launch";

export type BusinessType = "company" | "sole_trader" | "personal" | "accountant";
export const BUSINESS_TYPES: { value: BusinessType; label: string }[] = [
  { value: "company", label: "Limited company" },
  { value: "sole_trader", label: "Sole trader" },
  { value: "personal", label: "Personal" },
  { value: "accountant", label: "Accountant or bookkeeper" },
];

export type EarlyAccessForm = {
  name: string;
  email: string;
  business_type: BusinessType | ""; // "" until one is picked
  heard: string;
  consent: boolean;
  website: string; // honeypot
};

/** Same shape check as the runtime (no DNS): something@domain.tld, no spaces. */
export const looksLikeEmail = (s: string) => s.length <= 254 && /^[^\s@<>]+@[^\s@<>.]+(\.[^\s@<>.]+)+$/.test(s.trim());

/** POST /public/early-access. Resolves on success; throws an Error whose message is for people. */
export async function joinEarlyAccess(form: EarlyAccessForm, source: string): Promise<void> {
  let r: Response;
  try {
    r = await fetch(`${RUNTIME_URL}/public/early-access`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name.trim() || null,
        email: form.email.trim(),
        business_type: form.business_type,
        heard: form.heard.trim() || null,
        consent: form.consent,
        consent_text: CONSENT_TEXT,
        source,
        website: form.website || null,
      }),
    });
  } catch {
    throw new Error("Couldn't reach Accnomos. Check you're online and try again.");
  }
  if (r.ok) return;
  if (r.status === 503)
    throw new Error("Sign-ups aren't open on this server yet. Email admin@zaytunauk.co.uk and we'll add you by hand.");
  if (r.status === 429) throw new Error("Too many tries from this connection. Wait a minute and try again.");
  const detail = await r
    .json()
    .then((b: { detail?: unknown }) => (typeof b.detail === "string" ? b.detail : null))
    .catch(() => null);
  throw new Error(detail ?? "Something went wrong. Please try again.");
}
