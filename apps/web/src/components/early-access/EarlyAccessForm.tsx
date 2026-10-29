"use client";

import SignUpForm, { type SignUpCopy } from "@/components/sign-up/SignUpForm";
import { CONSENT_TEXT, joinEarlyAccess, SUCCESS_TEXT } from "@/lib/early-access";
import { useSubmissionMode } from "@/lib/submission-mode";

const COPY: SignUpCopy = {
  heading: "Get 3 months free at launch",
  intro: "Accnomos opens to everyone in November 2026. Join the early list and your first 3 months are free.",
  consent: CONSENT_TEXT,
  consentError: "Tick the box so we can send you the launch email",
  button: "Join the early list",
  busy: "Joining…",
  success: SUCCESS_TEXT,
  purpose: "to send that one email, and deletes them 12 months after launch unless you become a customer",
  submit: joinEarlyAccess,
};

/**
 * "Get 3 months free at launch": the pre-launch build's sign-up (POST /public/early-access). Renders nothing in the
 * submission build (NEXT_PUBLIC_SUBMISSION_MODE, default 1), which shows the neutral JoinForm for the same list.
 */
export default function EarlyAccessForm({ source }: { source: "/" | "/judges" }) {
  // Written out so the bundler folds it: a submission build that is not a test build never ships the form or its
  // pre-launch words (scripts/prelaunch-words.mjs). Test builds keep it so a spec can flip the mode per page.
  if (process.env.NEXT_PUBLIC_SUBMISSION_MODE !== "0" && process.env.NEXT_PUBLIC_TEST_MODE !== "1") return null;
  return <PreLaunchOnly source={source} />;
}

function PreLaunchOnly({ source }: { source: "/" | "/judges" }) {
  return useSubmissionMode() ? null : <SignUpForm copy={COPY} source={source} />;
}
