export const REPORT_PROBLEM_EVENT = "accnomos:report-problem";

let waiting = false;

/** Opens Help › Report a problem (components/billing/ReportProblem.tsx, loaded on first use by LazyDialogs). */
export function openReportProblem(): void {
  waiting = true; // for a dialog that is still loading: it takes this when it mounts
  window.dispatchEvent(new Event(REPORT_PROBLEM_EVENT));
}

/**
 * Whether the dialog has been asked for and not closed since. Kept until the dialog closes (reportClosed), so a dialog
 * that mounts late, or mounts again, still opens.
 */
export const reportRequested = (): boolean => waiting;

/** The dialog was closed. */
export function reportClosed(): void {
  waiting = false;
}
