import { postSignUp, type SignUpForm, type SignUpSource } from "@/lib/sign-up";

/** Must match CONSENT_TEXT in services/runtime/app/early_access.py: the runtime stores it with each sign-up and
 * refuses any other wording. Pre-launch build only (components/early-access/EarlyAccessForm.tsx). */
export const CONSENT_TEXT = "Email me once Accnomos launches, with my 3 months free. I can unsubscribe any time.";
export const SUCCESS_TEXT = "You're on the list — we'll email you once at launch";

/** POST /public/early-access. Resolves on success; throws an Error whose message is for people. */
export const joinEarlyAccess = (form: SignUpForm, source: SignUpSource) =>
  postSignUp("/public/early-access", form, CONSENT_TEXT, source);
