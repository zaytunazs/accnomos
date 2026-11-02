import type { RtGoalProgress, RtGoalsView } from "./goals";

/**
 * GET /books/goals for the fictional Bramblewood sample (signed out, on /try and /goals). SAMPLE — FICTIONAL
 * FIGURES: every amount here is invented, worked out the way services/runtime/app/goals.py would for 27 Oct 2026,
 * and the note is the code-written one the runtime gives when no AI is set up.
 */

const created = "2026-09-01T09:00:00Z";

const sales: RtGoalProgress = {
  goal: {
    id: "sample-sales",
    name: "October sales",
    kind: "earn",
    scope: "business",
    start: "2026-10-01",
    end: "2026-10-31",
    target_pence: 1500000,
    measure: "manual",
    saved_pence: 0,
    created_at: created,
  },
  kind_label: "Sales target",
  status: "at_risk",
  status_label: "At risk",
  tone: "warning",
  period_label: "1 Oct 2026 – 31 Oct 2026",
  current_pence: 1124000,
  target_pence: 1500000,
  target_label: "£15,000.00 sales target",
  plan_to_date_pence: 1306452,
  percent: 74,
  variance_pence: -182452,
  variance_text: "£1,824.52 behind plan to date.",
  needed_text: "£3,760.00 still to go by 31 Oct 2026.",
  run_rate_pence: 1290519,
  days_left: 4,
  as_of: "2026-10-27",
  source_text: "Sales in your approved ledger, before VAT from 1 Oct 2026; books through 27 Oct 2026",
  drivers: [],
  suggestions: ["£3,760.00 still to go by 31 Oct 2026."],
};

const materials: RtGoalProgress = {
  goal: {
    id: "sample-materials",
    name: "Keep materials under budget",
    kind: "spend_cap",
    scope: "business",
    start: "2026-10-01",
    end: "2026-10-31",
    target_pence: 900000,
    focus: "Materials",
    measure: "manual",
    saved_pence: 0,
    created_at: created,
  },
  kind_label: "Spending limit",
  status: "on_track",
  status_label: "On track",
  tone: "positive",
  period_label: "1 Oct 2026 – 31 Oct 2026",
  current_pence: 714000,
  target_pence: 900000,
  target_label: "£9,000.00 spending limit on Materials",
  plan_to_date_pence: 783871,
  percent: 79,
  variance_pence: 69871,
  variance_text: "£698.71 under plan to date.",
  needed_text: "£1,860.00 left to spend by 31 Oct 2026.",
  run_rate_pence: 819778,
  days_left: 4,
  as_of: "2026-10-27",
  source_text: "Approved purchases on Materials, before VAT, from 1 Oct 2026; books through 27 Oct 2026",
  drivers: [
    { name: "Oak boards", kind: "item", this_pence: 312000, before_pence: 268000, change_pence: 44000 },
    { name: "Wood glue", kind: "item", this_pence: 18400, before_pence: 12100, change_pence: 6300 },
    { name: "Hinges", kind: "item", this_pence: 41600, before_pence: 45200, change_pence: -3600 },
  ],
  suggestions: [
    "You have spent £3,120.00 on Oak boards so far, £440.00 more than the same number of days before.",
    "You have spent £184.00 on Wood glue so far, £63.00 more than the same number of days before.",
  ],
};

const van: RtGoalProgress = {
  goal: {
    id: "sample-van",
    name: "Van deposit",
    kind: "save",
    scope: "business",
    start: "2026-09-01",
    end: "2027-02-28",
    target_pence: 600000,
    measure: "manual",
    saved_pence: 150000,
    created_at: created,
  },
  kind_label: "Savings goal",
  status: "at_risk",
  status_label: "At risk",
  tone: "warning",
  period_label: "1 Sep 2026 – 28 Feb 2027",
  current_pence: 150000,
  target_pence: 600000,
  target_label: "£6,000.00 target",
  plan_to_date_pence: 188950,
  percent: 25,
  variance_pence: -38950,
  variance_text: "£389.50 behind plan to date.",
  needed_text: "£4,500.00 still to go: about £1,105.65 a month.",
  run_rate_pence: null,
  days_left: 124,
  as_of: "2026-10-27",
  source_text: "The amount you have recorded as put aside",
  drivers: [],
  suggestions: [
    "Record what you put aside as you go, so the progress stays current.",
    "£4,500.00 still to go: about £1,105.65 a month.",
  ],
};

export const sampleGoals: RtGoalsView = {
  today: "2026-10-27",
  household: false,
  sample: true,
  goals: [sales, materials, van],
  note: {
    note_md: "October sales is at risk. £3,760.00 still to go by 31 Oct 2026.",
    model: "code",
    fallback_reason: "Sample — fictional figures. Code wrote this note.",
  },
  facts: {},
};
