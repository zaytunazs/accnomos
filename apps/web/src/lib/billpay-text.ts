/** Words for upcoming PayPal bill payments, kept free of imports so tests/unit can load it directly. */

export const UPCOMING_STATUS: Record<"scheduled" | "planned" | "due_today" | "paying" | "paid" | "needs_you", string> = {
  scheduled: "Approved, waiting for its date",
  planned: "Needs your approval",
  due_today: "Due today",
  paying: "Paying",
  paid: "Paid",
  needs_you: "Needs you",
};

/** "Google Calendar" or "Outlook calendar": the calendar of the account the user signed in with. */
export function calendarName(kind: string): string {
  return kind === "google" ? "Google Calendar" : kind === "personal" || kind === "work" ? "Outlook calendar" : "your calendar";
}

/** The honest line for an approved payment: PayPal cannot hold a payment, so Accnomos pays it when next open. */
export function paysLine(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const when = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  return `Accnomos pays this the next time it is open on or after ${when} — PayPal cannot hold a payment for a future date.`;
}
