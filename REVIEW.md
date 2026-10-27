# Review: `claude/demo-dry-run`

Second pass over the demo dry run (`TASK_BRIEF.md`): `docs/DEMO.md` as one Playwright flow, the video stills, the doc
wording fixes, and the action card's sentence for an approval that stopped halfway.

## What was checked

- `pytest -q`: `services/runtime` 746 passed, 1 skipped; `services/hmrc-relay` 102; `packages/ledger` 35;
  `packages/connectors` 43. All green.
- `cd apps/web && pnpm run build`: clean.
- `pnpm run e2e`: 114 passed in about 80 s (38 desktop, 74 phone, 2 demo). The first full run, before my new test, was 113/113. Demo flow: desktop 5.2 s, phone
  5.1 s, so it stays in CI.
- Read the whole diff: the `demo` seed and per-tenant "today", the stub's demo receipt and invoice-intent pattern,
  `actions.propose` getting the same day as the rest of Ask, the verifier line no longer counting code checks twice,
  the action card's TTL timer and stale-approval text, and DEMO.md / VIDEO_SCRIPT.md against the spec's assertions.
- Every `shots/*.png` that VIDEO_SCRIPT.md links to exists, and each is under 400 kB (largest 108 kB). The spec also
  asserts the size.
- Product rules: nothing new is written server-side outside test mode. The model only returns an intent, and code
  prices the invoice. Nothing is sent before Approve (asserted). The fictional company and receipt are labelled.

## What I fixed

- `3a26633` web(ask): **a reload never brought the Ask thread back.** On mount the save effect wrote `[]` over
  sessionStorage before the thread was read. This bug was already on main. Also, the branch's new card timer counted
  15 minutes from mount, so a card restored after a reload got a fresh TTL and looked approvable when it had expired.
  Each turn now records when its answer arrived on the device, and the card times out from then (still unaffected by
  clock skew). New e2e test in `ask.spec.ts`; it fails without the fix.
- `1bcab26` web(ask): the stalled-approval line repeated the runtime's own advice and said "give it 10 minutes" even
  after the 10 minutes were up. Each 409 message now gets its own sentence. Under 10 minutes: wait and check before
  approving again. Once stale: check, Reject, and ask again only if it is not there. `docs/ACTIONS.md` and DEMO.md
  row 12 match.
- `2c7a07e` docs: the README "What works today" e2e row and `docs/DEV.md` now give today's counts and the `demo`
  project / `pnpm run e2e:demo`. The README security row no longer says the action card cannot explain a stuck
  approval.
- `e590f42` runtime(testmode): each demo-seeded tenant gets its own copy of the JM Trading contact, not one shared
  object.

## What remains

- Rows 8 (HMRC sandbox) and 13 (Android) are skipped in the dry run with the reason stated. They have not been
  rehearsed end to end in this branch.
- Test mode differs from the stage: the model is `accnomos-test-stub`, nothing is cropped, and timestamps in the stills
  are the real clock's, not 4 Nov 2026. The stills show this. Re-shoot on the live site if that matters for the video.
- The action card's Approve → send has only been run against the fake sender, not a real mailbox (DEMO.md setup
  step 4 says so).
- `TASK_BRIEF.md` is committed at the repo root (by the `wip` checkpoint commit `a66b5b5`). Drop it, or squash that
  commit, before merging if briefs should not live on main.
- The CI workflow has not been run on GitHub for this branch.

## How to verify by hand

`uv sync --all-packages --all-extras`, then `cd apps/web && pnpm install && pnpm run e2e`. Expect 114 passed and two
`demo · …: total ~5 s` lines. Then run `pnpm run e2e:demo`, which rewrites `docs/submission/shots/`, and compare the
stills with `docs/submission/VIDEO_SCRIPT.md`. To check the Ask fixes in the running test build: sign in, ask "send a
£100 invoice to JM Trading" (after `POST /__test/reset?seed=demo` and *Import from Outlook* on Contacts) and reload
`/ask`. The thread and card come back, and the card shows *This proposal has expired; ask again.* 15 minutes after it
first arrived, not 15 minutes after the reload.
