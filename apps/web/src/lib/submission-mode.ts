"use client";

import { useSyncExternalStore } from "react";

/**
 * NEXT_PUBLIC_SUBMISSION_MODE, inlined at build time: `1` (the default, also when unset) is the hackathon submission
 * build, `0` the public build with the pre-launch extras (the early-adopter form). Anything but "0" means submission
 * mode, so a build that forgets the flag shows judges exactly what they were promised.
 */
export const SUBMISSION_MODE_BUILD = process.env.NEXT_PUBLIC_SUBMISSION_MODE !== "0";

/** Test-mode builds only: e2e specs flip the mode per page without a second build (e2e/early-access.spec.ts). */
export const SUBMISSION_MODE_TEST_KEY = "accnomos.test.submission-mode";

function read(): boolean {
  // Written out (not a shared constant) so the bundler folds it: production builds never read localStorage here.
  if (process.env.NEXT_PUBLIC_TEST_MODE === "1") {
    try {
      const v = window.localStorage.getItem(SUBMISSION_MODE_TEST_KEY);
      if (v === "0" || v === "1") return v === "1";
    } catch {
      /* storage blocked: the build flag */
    }
  }
  return SUBMISSION_MODE_BUILD;
}

const subscribe = () => () => {};

/** Whether this is the submission build. Constant outside test mode; the static HTML uses the build flag. */
export function useSubmissionMode(): boolean {
  return useSyncExternalStore(subscribe, read, () => SUBMISSION_MODE_BUILD);
}
