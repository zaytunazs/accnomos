"use client";

import type { ReactNode } from "react";
import { useSubmissionMode } from "@/lib/submission-mode";

/**
 * Pre-launch copy (launch dates, the early-adopter list): shown only when this is not the submission build. Server
 * components wrap it as `{PRELAUNCH_IN_BUILD && <Prelaunch>…</Prelaunch>}` (lib/public-site.ts), so a submission
 * build leaves the words out of the HTML and its RSC payload too; test builds keep them for specs that flip the mode.
 */
export default function Prelaunch({ children }: { children: ReactNode }) {
  return useSubmissionMode() ? null : <>{children}</>;
}
