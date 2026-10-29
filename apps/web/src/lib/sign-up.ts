import { RUNTIME_URL } from "@/lib/ai-config";

/**
 * The "Get 3 months free" list (runtime app/early_access.py). Two forms feed it: the neutral one here, which every
 * build may show (POST /public/sign-up), and the pre-launch build's form (lib/early-access.ts). This module never
 * names a launch, so the submission build's bundle stays clear of pre-launch words (scripts/prelaunch-words.mjs).
 */

/** Must match SIGNUP_CONSENT_TEXT in services/runtime/app/early_access.py: stored with each sign-up, any other
 * wording is refused. */
export const SIGNUP_CONSENT_TEXT = "Email me to set up my 3 months free of Accnomos. I can unsubscribe any time.";
export const SIGNUP_SUCCESS_TEXT = "Thanks — we'll email you to set up your 3 months free";

export type BusinessType = "company" | "sole_trader" | "personal" | "accountant";
export const BUSINESS_TYPES: { value: BusinessType; label: string }[] = [
  { value: "company", label: "Limited company" },
  { value: "sole_trader", label: "Sole trader" },
  { value: "personal", label: "Personal" },
  { value: "accountant", label: "Accountant or bookkeeper" },
];

export type SignUpForm = {
  name: string;
  email: string;
  business_type: BusinessType | ""; // "" until one is picked
  heard: string;
  consent: boolean;
  website: string; // honeypot
};

/** The page a form was on, stored with the sign-up. */
export type SignUpSource = "/" | "/judges" | "/join";

/** Same shape check as the runtime (no DNS): something@domain.tld, no spaces. */
export const looksLikeEmail = (s: string) => s.length <= 254 && /^[^\s@<>]+@[^\s@<>.]+(\.[^\s@<>.]+)+$/.test(s.trim());

/** POST `path` on the runtime. Resolves on success; throws an Error whose message is for people. */
export async function postSignUp(path: string, form: SignUpForm, consentText: string, source: SignUpSource): Promise<void> {
  let r: Response;
  try {
    r = await fetch(`${RUNTIME_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name.trim() || null,
        email: form.email.trim(),
        business_type: form.business_type,
        heard: form.heard.trim() || null,
        consent: form.consent,
        consent_text: consentText,
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

/** The neutral form: POST /public/sign-up with SIGNUP_CONSENT_TEXT. */
export const joinList = (form: SignUpForm, source: SignUpSource) =>
  postSignUp("/public/sign-up", form, SIGNUP_CONSENT_TEXT, source);
