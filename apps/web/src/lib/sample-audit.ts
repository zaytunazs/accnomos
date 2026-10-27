import type { RtAuditEntry } from "./runtime";

/**
 * Shown on /audit when signed out: one working day at a fictional company, in the shapes GET /audit returns
 * (services/runtime/app/audit_view.py). Newest first.
 */
export const SAMPLE_AUDIT_DAY = "2026-10-14";

const refs = (r: Partial<RtAuditEntry["refs"]> = {}): RtAuditEntry["refs"] => ({
  proposal: null, event: null, invoice: null, action: null, file: null, ...r,
});
const you = "user:sam@sambuilds.example";
const at = (hhmm: string) => `${SAMPLE_AUDIT_DAY}T${hhmm}:00+01:00`;

export const sampleAudit: RtAuditEntry[] = [
  { ts: at("17:40"), actor: you, actor_kind: "user", actor_label: "You", event: "action_done",
    summary: "Approved from Ask: Logged 6 hours on Hartley kitchen refit", refs: refs({ action: "sample-action-1" }) },
  { ts: at("16:05"), actor: you, actor_kind: "user", actor_label: "You", event: "invoice_sent",
    summary: "Emailed invoice INV-0007 to accounts@harrogatedental.example", refs: refs({ invoice: "INV-0007" }) },
  { ts: at("14:20"), actor: you, actor_kind: "user", actor_label: "You", event: "undone",
    summary: "Undid the entry for Travis Perkins £212.40 that Autopilot posted; it is back in Review",
    refs: refs({ proposal: "sample-travis", event: "sample-event-2" }) },
  { ts: at("09:12"), actor: you, actor_kind: "user", actor_label: "You", event: "approved",
    summary: "Posted Screwfix £38.47 to the ledger", refs: refs({ proposal: "sample-screwfix-0", event: "sample-event-1" }) },
  { ts: at("08:31"), actor: "agent:autopilot", actor_kind: "agent", actor_label: "Autopilot", event: "approved",
    summary: "Posted Travis Perkins £212.40 to the ledger", refs: refs({ proposal: "sample-travis", event: "sample-event-2" }) },
  { ts: at("08:30"), actor: "agent:extractor", actor_kind: "agent", actor_label: "Reader", event: "proposed",
    summary: "Read Travis Perkins £212.40 and proposed an entry",
    refs: refs({ proposal: "sample-travis", file: "01 Receipts/2026-10/2026-10-13 Travis Perkins £212.40.jpg" }) },
  { ts: at("07:45"), actor: you, actor_kind: "user", actor_label: "You", event: "plan_applied",
    summary: "Applied the day plan for 2026-10-14: 3 entries", refs: refs() },
  { ts: at("07:15"), actor: "agent:intake", actor_kind: "agent", actor_label: "Intake", event: "mail_scanned",
    summary: "Checked Outlook: 2 saved from 5 candidates", refs: refs({ file: "00 Inbox" }) },
  { ts: at("07:00"), actor: "agent:triage", actor_kind: "agent", actor_label: "Triage", event: "mail_triaged",
    summary: "Sorted the inbox: 6 threads from 41 messages", refs: refs() },
];
