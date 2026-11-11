"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { PLAN_LIMIT_EVENT, currentPlanLimit } from "@/lib/plan-limit";
import { REPORT_PROBLEM_EVENT, reportRequested } from "@/lib/report-problem";

// The dialogs (and the API client they need) load the first time they are asked for, not with every page.
const PlanLimitDialog = dynamic(() => import("./PlanLimitDialog"), { ssr: false });
const ReportProblem = dynamic(() => import("./ReportProblem"), { ssr: false });

/**
 * Listens for the two global dialogs' events and mounts each dialog on first use. What woke a dialog is
 * kept (lib/billing.ts, lib/report-problem.ts) for it to take when it has loaded, so the first 402 is not lost.
 */
export default function LazyDialogs() {
  const [limit, setLimit] = useState(false);
  const [report, setReport] = useState(false);
  useEffect(() => {
    const onLimit = () => setLimit(true);
    const onReport = () => setReport(true);
    window.addEventListener(PLAN_LIMIT_EVENT, onLimit);
    window.addEventListener(REPORT_PROBLEM_EVENT, onReport);
    // A 402 or a Report a problem that came before this listened (on page load, before the sign-in check) still opens.
    queueMicrotask(() => {
      if (currentPlanLimit()) setLimit(true);
      if (reportRequested()) setReport(true);
    });
    return () => {
      window.removeEventListener(PLAN_LIMIT_EVENT, onLimit);
      window.removeEventListener(REPORT_PROBLEM_EVENT, onReport);
    };
  }, []);
  return (
    <>
      {limit && <PlanLimitDialog />}
      {report && <ReportProblem />}
    </>
  );
}
