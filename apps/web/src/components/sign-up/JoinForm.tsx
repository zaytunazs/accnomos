"use client";

import SignUpForm, { type SignUpCopy } from "@/components/sign-up/SignUpForm";
import { joinList, SIGNUP_CONSENT_TEXT, SIGNUP_SUCCESS_TEXT, type SignUpSource } from "@/lib/sign-up";
import { useSubmissionMode } from "@/lib/submission-mode";

/** No launch, beta or waiting-list wording: the submission build shows this (scripts/prelaunch-words.mjs). */
const COPY: SignUpCopy = {
  heading: "Join the waiting list",
  intro: "Leave your email to join the waiting list.",
  consent: SIGNUP_CONSENT_TEXT,
  consentError: "Tick the box so we can email you",
  button: "Join the waiting list",
  busy: "Sending…",
  success: SIGNUP_SUCCESS_TEXT,
  purpose: "to email you when your place on the waiting list comes up, and deletes them by the end of November 2027",
  submit: joinList,
};

/**
 * "Join the waiting list" (POST /public/sign-up, the same list as the pre-launch form). `everyBuild` shows it in the
 * pre-launch build too (/join); without it, the pre-launch build shows its own EarlyAccessForm instead (landing page).
 */
export default function JoinForm({ source, everyBuild = false }: { source: SignUpSource; everyBuild?: boolean }) {
  const submission = useSubmissionMode();
  return everyBuild || submission ? <SignUpForm copy={COPY} source={source} /> : null;
}
