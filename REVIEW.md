# Review: `claude/autopilot-rules` (Autopilot L1)

Second-agent review of the implementation of `TASK_BRIEF.md`: "Always do this for &lt;supplier&gt;" rules, auto-approval with audit, and undo by reversal.

## What was checked

- **Tests, all green after the fixes:** `services/runtime` 60 passed (57 before plus 3 new), `packages/connectors` 12, `packages/ledger` 15,
  `services/hmrc-relay` 39. `apps/web`: `pnpm run build` compiles and prerenders all 14 routes.
- **Runtime diff** (`autopilot.py`, `approve.py`, `inbox.py`, `books.py`, `routes_books.py`, `schemas.py`):
  - Auto-approval goes through the same `approve()` as the Approve button, and the event has `approved_by: "autopilot"`.
  - Refusal reasons are all present: a check warns or fails; the gross is over 2× typical (exactly 2× is allowed); the VRN differs (one side missing counts as different); the VAT treatment differs; it is a sale; Autopilot is switched off.
  - Amounts are pence integers throughout.
  - Undo appends a reversal with a deterministic id, so a retry cannot double-post. It refuses to undo a reversal, an entry that is already undone, or an entry that is bank-matched.
  - Re-approving after an undo gets a fresh event id.
  - Route inputs are validated: event ids must be hex, and supplier keys must match `KEY_RE` (path traversal returns 404).
  - Nothing is stored server-side: rules, audit lines and events all live in the user's storage.
- **Web diff:**
  - The checkbox is wired to `remember`.
  - "Approved by Autopilot (n)" lists the last 30 days, each with Undo.
  - Settings shows the real rules from `GET /books/rules`, with Remove, and a localStorage switch that sends `X-Autopilot: off` on scan only. CORS allows the header and DELETE.
  - UK English is fine. No secrets.
- **Docs:** the README row and `docs/AUTOPILOT.md` match the code. The README says "end-to-end run pending", and the doc's "Not yet" section covers the dating of reversals in periods already submitted to HMRC.

## What I fixed

- `3580b59`: **Bug.** `confirm_match` accepted an undone entry, or the reversal itself, so a bank line could be matched to something that no longer stands. Undo already blocked the opposite direction. Added `Books.live_events()`, which both suggestions and confirmation now use. New tests:
  - undo is refused while a bank line is matched, works after unmatching, and afterwards neither event can be matched;
  - a hand-edited invalid rule in `rules.json` is skipped and scanning still auto-approves;
  - an `ApprovalError` during an Autopilot post leaves the proposal in Review with "Could not post: …", and writes no event, no autopilot audit line and no hit.
- `fc6d423`: **Wording.** Approving a sales invoice with "Always do this" ticked showed "Autopilot will do this … next time", but no rule is made for sales. It now says rules are for purchases only.
- The REVIEW.md commit also adds one line to `docs/AUTOPILOT.md` about bank matching after an undo.

## What remains

- Not run end to end against real OneDrive/Graph or in a browser. All runtime tests use `FakeStorageProvider` and a stubbed extractor.
- The Autopilot audit is written to `_System/audit/autopilot/` (lower-case, beside the existing `_System/audit/`). The brief says `_System/Audit/autopilot/`. These are the same folder on OneDrive, which ignores case, but they are not the same on a case-sensitive local filesystem. Documented, not changed.
- A reversal is dated like the original. Undoing an entry in a VAT period already submitted to HMRC would change that period's figures. There is no period lock yet; this is documented under "Not yet" in `docs/AUTOPILOT.md`.
- After an undo, the proposal keeps its old `autopilot` decision (`auto_approve: true`). Review doesn't show it (the banner only shows refusals), but the stored JSON is stale until the user decides again.
- The Settings "Autopilot level" (L0/L1/L2) selector still has the sample description "auto-posts … under £250" and does not control anything. The on/off switch is the only real control. Documented in `docs/AUTOPILOT.md`.
- The "Always do this" checkbox still appears on sales-invoice cards (it saves no rule there). Hiding it needs a `ProposalCard` prop.
- The Undo list loads every posted proposal (`?status=posted`) and filters on the client. This is fine at small volumes; it needs a server-side filter later.

## How to verify by hand

1. Start the runtime and the web app (`docs/DEV.md`) and sign in with a test OneDrive.
2. Drop a clear purchase receipt (one with a VAT number) into `00 Inbox`, scan, tick "Always do this for &lt;supplier&gt;" and Approve. Check that `_System/Rules/rules.json` appears in OneDrive, and that Settings › Autopilot rules lists it.
3. Drop a second receipt from the same supplier at a similar amount and scan. The note should say "1 approved by Autopilot". The entry should appear under "Approved by Autopilot (1)", with one line in `_System/audit/autopilot/<yyyy-mm>.jsonl`.
4. Press Undo. A `kind: "reversal"` event should be added (the original file is untouched), the proposal should be back in Review, and the VAT page for that period should not count it.
5. Try a receipt from that supplier for more than twice the amount, then one scanned with Autopilot switched off in Settings. Both must wait in Review, each with an "Autopilot left this for you" line giving the reason.
