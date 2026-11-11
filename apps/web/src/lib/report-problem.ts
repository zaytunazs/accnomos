export const REPORT_PROBLEM_EVENT = "accnomos:report-problem";

let waiting = false;

/** Opens Help › Report a problem (components/billing/ReportProblem.tsx, loaded on first use by LazyDialogs). */
export function openReportProblem(): void {
  waiting = true; // for a dialog that is still loading: it takes this when it mounts
  window.dispatchEvent(new Event(REPORT_PROBLEM_EVENT));
}

/** True once if the dialog was asked for before it was mounted. */
export function takeReportRequest(): boolean {
  const w = waiting;
  waiting = false;
  return w;
}
