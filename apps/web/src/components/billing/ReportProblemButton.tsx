"use client";

import { openReportProblem } from "@/lib/report-problem";
import { useSignedIn } from "@/lib/signed-in";

/** Help › Report a problem (the dialog is mounted by AppShell, so it is there only while signed in). */
export default function ReportProblemButton() {
  const signedIn = useSignedIn();
  if (signedIn !== true) return null; // the dialog needs an account to send from
  return (
    <button
      type="button"
      onClick={() => openReportProblem()}
      className="mt-3 h-11 rounded-xl border-2 border-teal bg-white px-4 text-[15px] font-bold text-teal-dark hover:bg-teal-tint"
    >
      Report a problem
    </button>
  );
}
