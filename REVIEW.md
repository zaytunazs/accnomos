# Review: `claude/review-page`

Second-agent review of the Web Review page work (brief: `TASK_BRIEF.md`). Reviewed on 27 Oct 2026. Nothing pushed.

## What was checked

- `services/runtime`: `pytest -q`: 633 passed, 1 skipped (632 before the two tests added here). No other package or service
  is touched by this branch, so `packages/*` and `services/hmrc-relay` were not re-run.
- `apps/web`: `pnpm run build` clean. `npx eslint src`: 0 errors, 1 warning, in `components/ask/AskThread.tsx`, which this branch
  does not touch. `tsc --noEmit` clean.
- `apps/web`: `pnpm run e2e` (Chromium, test-mode runtime): **27 passed, 4 failed** (before this review: 26 passed, 5 failed).
  All 7 tests in `review.spec.ts` and the 390 px Review test in `phone.spec.ts` pass. The 4 failures are listed under *What remains*.
- Read the whole diff against `origin/main`. Checked: pence maths (`review-edit.ts` parses to integer pence; VAT tolerance
  matches `checks.py` `VAT_MATH`), the `edits` keys against `approve.py` `DOC_EDITS` (+ `account`, `job_id`, `vehicle_id`),
  rule matching against `autopilot.py`, `file_path` in `schemas.py`, no raw check codes on screen, the
  *SAMPLE — FICTIONAL COMPANY* label, no user data written server-side, and no new runtime route (bulk approval is one
  `POST …/approve` per proposal).
- The test-mode change in `ai/config.py` (skip the AI base-URL allow-list) is safe: in test mode `resolve()` throws the URL
  away and uses the stub, and test mode is pinned off in the Docker image.

## What was fixed

| Commit | Fix |
|---|---|
| `5f8a52d` | Runtime tests for the two runtime changes on the branch: test mode accepts any `X-AI-Base-Url` but still resolves to the stub (and outside test mode it is still refused), and the fake Graph `:/content` read returns the file's bytes and MIME type, or 404. |
| `7655050` | `POST /ai/test` checked the allow-list before swapping in the stub in test mode: the same bug `051009e` fixed for scans. The e2e `connect` test failed with "runtime returned 400"; it passes now. |
| `b3ba91f` | Signed-out sample: Reject told the user the document was "parked in 04 Needs a look" and could not be undone, which is untrue for a sample that stays in the tab. The sample now undoes rejections too, and the confirm text depends on the backend. If one reversal in an *Approve all* batch undo failed, the history kept the handles already reversed, so pressing U again would try to reverse them a second time; it now keeps only what is still posted. The e2e test covers sample reject → U. |
| `b3ba91f`, `22885d0` | e2e flake: the runtime's first scan builds the stub's gold-receipt caches and took over 10 s cold (then about 1.5 s). The signed-in Review test failed whenever it was the first scan. The scan step now waits up to 30 s. `review-vat` also needed `.first()` on the upload input, because the empty state now has its own upload button. |
| `49ee3c0` | `docs/AUTOPILOT.md`: how Review shows L1 rule matches and *Approve all N rule matches*. |
| `3fa548d` | README *What works today*: a Review page row that claims only Playwright on the test-mode runtime, not a real OneDrive. |

## What remains

- **4 e2e failures that this branch did not cause.** Each fails on a page the branch does not touch, and each spec predates
  the branch. Probable cause: `main` moved on and these specs did not follow. Not confirmed by running them on `origin/main`.
  - `settings.spec.ts` and `outlook.spec.ts`: no *Autopilot level* radio group or *Outlook intake* switch on `/settings`
    (Settings became tabbed in `10baa67`).
  - `ask.spec.ts` and `review-vat.spec.ts`: they expect VAT and Ask to default to Jul–Sep 2026 (`key 26A3`), but `/vat` now
    opens on the current period, Oct–Dec 2026. `review-vat` fails at that `/vat` step, before its Review steps. The Review
    steps after it were updated, but have not run green here end to end.
- With *Always do this for …* ticked on a sample card, the note says "Autopilot will do this for … next time", but the sample
  saves no rule. The banner says nothing leaves the tab, but this line overclaims.
- The verifier is not part of the browser-side rule match (`review-rules.ts`). It relies on a disagreement already failing a
  check, so a proposal with no second reading and no failing check could be offered as a rule match where `autopilot.py`
  would not post it. Approval is still the user's, one at a time through `POST …/approve`.
- The edit sheet cannot send VAT code or VAT number corrections (the runtime keeps both as read). It says so and blocks the
  save; changing that needs a runtime change.
- No browser unit-test runner in `apps/web`: `review-edit.ts` and `review-rules.ts` are covered only through Playwright.
- Nothing has been run against a real OneDrive, a real model or a real browser by hand.

## How to verify by hand

Signed out, open `/review` (`cd apps/web && pnpm dev`). You should see the *SAMPLE — FICTIONAL COMPANY · Bramblewood Joinery
Ltd.* banner and 4 cards. Press J to focus the first Screwfix card, A to approve it (the next card takes focus), and U to bring
it back. Press R and confirm, then U again. Click *Approve all 2 rule matches* and confirm once; both Screwfix cards go, and U
brings both back. On Novex, click the thumbnail: the original sits beside the crop with "Cropped by code"; click either to
zoom, and Esc closes it. Press E on Novex: the date field is highlighted with the second reading, and *Save & approve* stays
disabled with a reason until the date is not in the future. Change the total so net + VAT no longer adds up and check the
reason updates. At 390 px wide (devtools), there is no horizontal scroll and Approve / Edit / Reject stay on one line. Signed
in against a real books folder, upload a receipt, scan, open the preview (it should read the file from OneDrive), edit one
field and *Save & approve*. In the network tab, the approve body should hold only that field in `edits`. Press U and check a
reversal appears in `_System/Ledger/events`.
