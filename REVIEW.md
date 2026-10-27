# Review: `claude/bank-ui`

Bank statements in the web app (F7): CSV upload, matches, confirm, unmatched actions, "Reconciled to date", Books.xlsx `Bank` sheet.
Brief: `TASK_BRIEF.md`. Reviewed on 27 Oct 2026 by a second agent.

## What was checked

- **Tests, run against this checkout.** The shared `.venv` has editable installs pointing at another checkout (`repo-lane-e`), so a
  plain `pytest` here imports the wrong `accnomos_ledger` and fails at collection. Each suite was run with
  `pytest -o pythonpath="<this checkout's src dirs>"`:
  `packages/ledger` 30 passed · `packages/connectors` 17 passed · `services/runtime` 136 passed · `services/hmrc-relay` 39 passed.
- **Web:** `cd apps/web && pnpm run build` passes; `eslint` is clean on `src/components/bank`, `src/lib/runtime.ts` and `src/app/bank`.
- **Diff read as a reviewer:** header sniffing and bank detection, ±1p / ±5 days / counterparty scoring (including the
  abbreviation and near-spelling rule), sha256 idempotency, the confirm/unmatch/transfer/ignore/expense-proposal endpoints
  (404/409 at the boundary), `reconciled_to`, the Books.xlsx `Bank` and `Summary` rows, and the `/bank` page.
- **Product rules:** nothing posts to the ledger from `/books/bank/*`. The expense proposal is `needs_a_look` with no VAT
  reclaimed and waits on /review for a person to approve it. Autopilot only acts on scanned inbox documents, so it never
  approves these proposals. Amounts stay in integer pence end to end. No secrets, and nothing is stored outside the user's
  own folder. The gold set is labelled `SAMPLE - FICTIONAL COMPANY`.

## What I fixed

- `d7431ca`: **A rejected expense proposal no longer blocks its line.** Before this fix, rejecting the proposal on /review
  left `/bank` saying "An expense proposal is waiting" with the button disabled, and the runtime returned the rejected
  proposal when asked again. `/books/bank/unmatched` now returns `proposal_status`. A new request after a reject makes a fresh
  proposal. The page shows "waiting" only while the proposal is open. A test was added. The same commit also:
  - shows the busy mark on the button actually pressed;
  - stops the Unmatched tile saying "Need an action" when only suggestions are open;
  - makes undoing an open line say "still open; there is nothing to undo".
- `0985198`: **Gold README wording.** The bank CSVs were described as "fictional", but the card payees (Screwfix, Shell,
  Adobe, …) are real UK merchants. The README now says which parts are made up.
- `9f4a3df`: **New `reconciled_to` unit test.** It covers no lines, a half-settled day, and a suggestion not counting as a
  decision.

## What remains

- **Folder name differs from the brief.** The brief asks for `02 Bank/<yyyy-mm-dd>_<bank>.csv`. The code files statements in
  the repo's existing layout instead: `03 Bank statements/<last date>_<bank>.csv`. README and code agree; the brief does not.
  Keep it unless the folder layout is meant to change everywhere.
- **Column layouts are modelled, not verified.** The Barclays/Starling/Tide/Monzo layouts follow the public export formats.
  None has been checked against a real export, and bank detection falls back to `bank` for unknown headers.
- **Re-exports with a different hash.** If a statement's lines were all imported before (an overlapping export with a
  different sha256), the CSV is still filed but has no stored lines. It then does not appear under Statements.
- **"Confirm all" and penny-out matches.** "Confirm all N exact matches" includes matches that are 1p out (they score ≥0.9 with
  a name match). The reason shown says "1p out", but they are confirmed in bulk.
- **Unused filename on bank-line proposals.** `suggested_filename` ends in `.csv` and uses the raw description. Nothing reads
  it today, because these proposals have no file, but it would need cleaning if a file is ever attached.
- **Not run against real services.** Nothing has run against a real OneDrive / Graph account, and the `/bank` page has not
  been clicked through in a browser.
- **ruff not run.** It needed a permission this session did not have.

## How to verify by hand

1. Sign in on the web app with a test OneDrive and post a few receipts, for example by approving the sample documents on Review.
2. Open **Bank** in the nav and drop `evals/gold/bank/barclays.csv` on the upload box. It should report 6 new lines saved as
   `03 Bank statements/2026-10-20_barclays.csv`, and that file should appear in OneDrive. Drop the same file again: it should
   say "already imported — nothing changed".
3. On **Matches**, confirm a row. It moves to **Done**, and *Undo* there reopens it.
4. On **Unmatched**:
   - mark "TO SAVINGS…" as a transfer;
   - create an expense proposal for "BUSINESS ACCOUNT FEE", then reject it on Review. Back on Bank, the button should be
     available again;
   - create another proposal and approve it. The line should reappear under Matches as an exact match.
5. Once everything up to a day is settled, the *Reconciled to date* tile shows that day. Open `Books.xlsx` and check the
   `Bank` sheet (status, matched event, expense proposal) and the `Summary` row "Bank reconciled to".
