"use client";

import SignUpForm, { type SignUpCopy } from "@/components/sign-up/SignUpForm";
import { joinList, SIGNUP_CONSENT_TEXT, SIGNUP_SUCCESS_TEXT, type SignUpSource } from "@/lib/sign-up";
import { useSubmissionMode } from "@/lib/submission-mode";

/** No launch, beta or waiting-list wording: the submission build shows this (scripts/prelaunch-words.mjs). */
const COPY: SignUpCopy = {
  heading: "Get 3 months free",
  intro: "Leave your email and we will set you up with 3 months free.",
  consent: SIGNUP_CONSENT_TEXT,
  consentError: "Tick the box so we can email you",
  button: "Get 3 months free",
  busy: "Sending…",
  success: SIGNUP_SUCCESS_TEXT,
  purpose: "to email you to set up your 3 months free, and deletes them by the end of November 2027 unless you become a customer",
  submit: joinList,
};

/**
 * "Get 3 months free" (POST /public/sign-up, the same list as the pre-launch form). `everyBuild` shows it in the
 * pre-launch build too (/join); without it, the pre-launch build shows its own EarlyAccessForm instead (landing page).
 */
export default function JoinForm({ source, everyBuild = false }: { source: SignUpSource; everyBuild?: boolean }) {
  const submission = useSubmissionMode();
  return everyBuild || submission ? <SignUpForm copy={COPY} source={source} /> : null;
}
