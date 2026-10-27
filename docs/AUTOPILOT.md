# Autopilot L1: "Always do this for &lt;supplier&gt;"

Accnomos proposes and you approve. Autopilot L1 lets you say, once, "next time this supplier sends
the same kind of receipt, post it the way I just did". It never invents a rule, and it never posts
anything that a code check is unsure about.

## What it does

1. **You teach it.** In Review, tick *Always do this for Screwfix* and tap Approve. Alongside the
   posting, Accnomos writes a rule to your own folder, `_System/Rules/rules.json`:

   ```jsonc
   {
     "supplier_key": "screwfix",            // normalised name: "SCREWFIX LTD." and "Screwfix" are the same
     "supplier_name": "Screwfix",
     "category": "Tools & small equipment",
     "account": "5100 Tools & small equipment",
     "vat_code": "S",                       // VAT codes on the expense lines of that approval
     "side": "purchase",
     "typical_gross_pence": 3847,           // the total you approved; Autopilot never changes it
     "vrn": "GB232456789",                  // supplier VAT number on that receipt, or null
     "created_at": "2026-10-27T10:12:00Z",
     "created_from_proposal_id": "…",
     "created_by": "you@example.co.uk",
     "hits": 0                              // how many times Autopilot has used it
   }
   ```

   One rule per supplier: ticking the box again replaces the rule.
   It also keeps the existing account rule (`_System/rules.json`), which files that supplier to the same account.

2. **It checks.** On each later scan, a new proposal from that supplier is posted automatically
   **only if all of these hold**:
   - Autopilot is on (Settings › Autopilot rules; the app sends `X-Autopilot: off` when it's off);
   - it is a purchase, like the rule;
   - **every** code check passed: no failure **and no warning** (low confidence, line detail that
     doesn't add up, duplicate file, non-GBP, bad VAT number… any of them stops it);
   - the supplier's VAT number is the one on the rule (missing on one side counts as different);
   - the VAT treatment (S/R/Z/N…) is the rule's;
   - the total is above zero and **no more than 2×** the rule's typical amount.

   Anything else waits in Review as normal, with a line saying why Autopilot left it for you.

3. **It posts the normal way.** A match goes through the same approval code as your Approve button.
   The ledger event says `approved_by: "autopilot"`. One line goes to your audit trail
   (`_System/audit/{yyyy-mm}.jsonl`, actor `autopilot`), and one goes to
   `_System/audit/autopilot/{yyyy-mm}.jsonl` with the amounts, the rule and the reasons.
   OneDrive paths ignore case, so this is the `_System/Audit/autopilot/` folder.

4. **You can undo.** Review lists *Approved by Autopilot (n)* for 30 days, each with **Undo**.
   Undo (`POST /books/undo/{event_id}`) **adds** a reversing ledger event: same date, every line on
   the other side, `kind: "reversal"`, `reverses: <event id>`. The proposal goes back to Review for
   you to decide again. Nothing is edited or deleted. The VAT return for that period nets to zero.
   Undo also works for entries you approved yourself. It is refused if a bank line is matched to the
   entry (unmatch it first) or if the entry has already been undone. Once undone, neither the entry
   nor its reversal can be matched to a bank line.

## What it never does

- Never creates a rule on its own: only your ticked approval does.
- Never auto-approves when any check fails **or warns**.
- Never auto-approves above 2× the typical amount, or when the VAT number or VAT treatment differs.
- Never auto-approves sales invoices (no rules are made from them).
- Never raises its own limit: `typical_gross_pence` changes only when you approve with the box ticked again.
- Never deletes or edits a ledger event: undo is a new, reversing event.
- Never keeps anything on our side: rules, audit lines and events all live in your OneDrive.

## API

| Call | What |
|---|---|
| `POST /books/approve/{id}` `{ "remember": true }` | Approve and save/replace the rule (`/books/proposals/{id}/approve` with `always` still works) |
| `POST /books/scan` (+ `X-Autopilot: off`) | Scan; matching clean proposals come back `status: "posted"`, `decided_by: "autopilot"`, with `autopilot: { auto_approve, reasons }` |
| `POST /books/undo/{event_id}` | Reversal event + proposal back in Review; 409 if already undone or bank-matched |
| `GET /books/rules` · `DELETE /books/rules/{supplier_key}` | List rules · remove one (and the account rule saved with it) |

Code: `services/runtime/app/autopilot.py` (rules and the decision), `app/inbox.py` (posting during a scan),
`app/approve.py` (`approve`, `undo`). Tests: `services/runtime/tests/test_autopilot.py`.

## Not yet

- The reversal is dated like the original. If that VAT period has already been submitted, check the
  return before undoing: the correction then belongs in the current period.
- Rule-based posting happens only at Settings › Autopilot level **L2**. The default is L1 (propose only),
  so a new user never has anything posted without approving it; the on/off switch on the rules card is the
  same setting.
