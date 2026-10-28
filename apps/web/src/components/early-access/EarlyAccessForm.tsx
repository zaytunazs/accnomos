"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import {
  BUSINESS_TYPES,
  CONSENT_TEXT,
  joinEarlyAccess,
  looksLikeEmail,
  SUCCESS_TEXT,
  type EarlyAccessForm as Form,
} from "@/lib/early-access";
import { useSubmissionMode } from "@/lib/submission-mode";

type Errors = Partial<Record<"email" | "business_type" | "consent", string>>;

const input =
  "mt-1 w-full rounded-xl border border-border bg-white px-3 py-2.5 text-[15px] text-ink aria-[invalid=true]:border-warn-ink";

/**
 * "Get 3 months free at launch": the early-adopter sign-up (POST /public/early-access). Renders nothing in the
 * submission build (NEXT_PUBLIC_SUBMISSION_MODE, default 1). The consent box starts unticked and its wording is
 * stored with the sign-up; the short notice under it is the point-of-collection privacy information (/privacy).
 */
export default function EarlyAccessForm({ source }: { source: "/" | "/judges" }) {
  // Written out so the bundler folds it: a submission build that is not a test build never ships the form or its
  // pre-launch words (scripts/prelaunch-words.mjs). Test builds keep it so a spec can flip the mode per page.
  if (process.env.NEXT_PUBLIC_SUBMISSION_MODE !== "0" && process.env.NEXT_PUBLIC_TEST_MODE !== "1") return null;
  return <SignUp source={source} />;
}

function SignUp({ source }: { source: "/" | "/judges" }) {
  const submission = useSubmissionMode();
  const id = useId();
  const [form, setForm] = useState<Form>({ name: "", email: "", business_type: "", heard: "", consent: false, website: "" });
  const [errors, setErrors] = useState<Errors>({});
  const [failed, setFailed] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const doneRef = useRef<HTMLParagraphElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const typeRef = useRef<HTMLInputElement>(null);
  const consentRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (done) doneRef.current?.focus(); // the form is gone: keep keyboard and screen-reader focus on the answer
  }, [done]);

  if (submission) return null;

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (key in errors) setErrors((e) => ({ ...e, [key]: undefined }));
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const next: Errors = {};
    if (!looksLikeEmail(form.email)) next.email = "Enter an email address like name@example.co.uk";
    if (!form.business_type) next.business_type = "Choose the one that fits best";
    if (!form.consent) next.consent = "Tick the box so we can send you the launch email";
    setErrors(next);
    setFailed(null);
    if (next.email) return emailRef.current?.focus();
    if (next.business_type) return typeRef.current?.focus();
    if (next.consent) return consentRef.current?.focus();
    setBusy(true);
    try {
      await joinEarlyAccess(form, source);
      setDone(true);
    } catch (err) {
      setFailed(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const heading = `${id}-heading`;
  return (
    <section aria-labelledby={heading} className="relative rounded-2xl border border-border bg-white p-5 sm:p-6">
      <h2 id={heading} className="text-xl font-extrabold tracking-tight text-ink">
        Get 3 months free at launch
      </h2>
      {done ? (
        <p ref={doneRef} tabIndex={-1} role="status" className="mt-3 rounded-xl bg-teal-tint px-4 py-3 text-[15px] font-bold text-teal-dark">
          {SUCCESS_TEXT}
        </p>
      ) : (
        <>
          <p className="mt-1 text-[14px] leading-relaxed text-muted">
            Accnomos opens to everyone in November 2026. Join the early list and your first 3 months are free.
          </p>
          <form noValidate onSubmit={submit} className="mt-4 grid gap-4 min-[640px]:grid-cols-2" aria-describedby={`${id}-notice`}>
            <div>
              <label htmlFor={`${id}-email`} className="text-sm font-bold text-ink">
                Email
              </label>
              <input
                ref={emailRef}
                id={`${id}-email`}
                type="email"
                inputMode="email"
                autoComplete="email"
                required
                maxLength={254}
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                aria-invalid={errors.email ? true : undefined}
                aria-describedby={errors.email ? `${id}-email-error` : undefined}
                className={input}
              />
              {errors.email && (
                <p id={`${id}-email-error`} className="mt-1 text-[13px] font-semibold text-warn-ink">
                  {errors.email}
                </p>
              )}
            </div>
            <div>
              <label htmlFor={`${id}-name`} className="text-sm font-bold text-ink">
                Name <span className="font-semibold text-muted">(optional)</span>
              </label>
              <input
                id={`${id}-name`}
                autoComplete="name"
                maxLength={100}
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                className={input}
              />
            </div>
            <fieldset
              className="min-[640px]:col-span-2"
              aria-describedby={errors.business_type ? `${id}-type-error` : undefined}
            >
              <legend className="text-sm font-bold text-ink">What are the books for?</legend>
              <div className="mt-1 grid grid-cols-1 gap-2 min-[400px]:grid-cols-2">
                {BUSINESS_TYPES.map((t, i) => (
                  <label
                    key={t.value}
                    className="flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border px-3 py-2 text-[14px] font-semibold text-ink has-[:checked]:border-teal has-[:checked]:bg-teal-tint"
                  >
                    <input
                      ref={i === 0 ? typeRef : undefined}
                      type="radio"
                      name={`${id}-type`}
                      value={t.value}
                      checked={form.business_type === t.value}
                      onChange={() => set("business_type", t.value)}
                      className="size-4 accent-teal"
                    />
                    {t.label}
                  </label>
                ))}
              </div>
              {errors.business_type && (
                <p id={`${id}-type-error`} className="mt-1 text-[13px] font-semibold text-warn-ink">
                  {errors.business_type}
                </p>
              )}
            </fieldset>
            <div className="min-[640px]:col-span-2">
              <label htmlFor={`${id}-heard`} className="text-sm font-bold text-ink">
                How did you hear about us? <span className="font-semibold text-muted">(optional)</span>
              </label>
              <input
                id={`${id}-heard`}
                maxLength={200}
                value={form.heard}
                onChange={(e) => set("heard", e.target.value)}
                className={input}
              />
            </div>
            {/* Honeypot: off-screen and out of the tab order; people never see it, form-filling bots do. */}
            <div aria-hidden="true" className="absolute -left-[10000px] h-px w-px overflow-hidden">
              <label htmlFor={`${id}-website`}>Website</label>
              <input
                id={`${id}-website`}
                name="website"
                tabIndex={-1}
                autoComplete="off"
                value={form.website}
                onChange={(e) => set("website", e.target.value)}
              />
            </div>
            <div className="min-[640px]:col-span-2">
              <label className="flex cursor-pointer items-start gap-3 text-[15px] font-semibold leading-snug text-ink">
                <input
                  ref={consentRef}
                  type="checkbox"
                  checked={form.consent}
                  onChange={(e) => set("consent", e.target.checked)}
                  aria-invalid={errors.consent ? true : undefined}
                  aria-describedby={errors.consent ? `${id}-consent-error` : undefined}
                  className="mt-0.5 size-5 shrink-0 accent-teal"
                />
                <span>{CONSENT_TEXT}</span>
              </label>
              {errors.consent && (
                <p id={`${id}-consent-error`} className="mt-1 pl-8 text-[13px] font-semibold text-warn-ink">
                  {errors.consent}
                </p>
              )}
            </div>
            <div className="flex flex-col gap-3 min-[640px]:col-span-2">
              {failed && (
                <p role="alert" className="rounded-xl border border-warn-border bg-warn-bg px-4 py-3 text-[14px] font-semibold text-warn-ink">
                  {failed}
                </p>
              )}
              <button
                type="submit"
                disabled={busy}
                className="self-start whitespace-nowrap rounded-xl bg-teal px-5 py-2.5 text-sm font-bold text-white hover:bg-teal-dark disabled:opacity-60"
              >
                {busy ? "Joining…" : "Join the early list"}
              </button>
              <p id={`${id}-notice`} className="text-[13px] leading-relaxed text-muted">
                Zaytuna Business Services Ltd keeps these details only to send that one email, and deletes them 12 months
                after launch unless you become a customer. To unsubscribe or be removed, email{" "}
                <a className="font-semibold text-teal-dark underline" href="mailto:admin@zaytunauk.co.uk">
                  admin@zaytunauk.co.uk
                </a>
                . More in our{" "}
                <Link className="font-semibold text-teal-dark underline" href="/privacy#early-access">
                  privacy policy
                </Link>
                .
              </p>
            </div>
          </form>
        </>
      )}
    </section>
  );
}
