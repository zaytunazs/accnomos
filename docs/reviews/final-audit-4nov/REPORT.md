# Final whole-system audit, 4 Nov 2026

Run on the day of the deadline (Wed 4 Nov 2026, 21:00 ET = 02:00 UK on 5 Nov) by a second agent that had not written
the code, from a fresh worktree of `main` at `8debc2e9` (09:42 UTC); its doc fixes were merged into `main` the same
afternoon with the fixes below. Everything marked **verified** was run or opened by the audit; everything marked
**not verified** was not, whatever other documents say.

## What was checked

| Area | How | Result |
|---|---|---|
| Live site and API (`https://accnomos.com`, `https://api.accnomos.com`) | A fresh company demo session at 11:00 UK from a browser: Home, Review (approve a pre-read document), Ask (typed), the Talk card, Reports › Export, VAT › *Make an HMRC sandbox test user*, Bank (the TrueLayer card: label, `john` / `doe`, *Connect the test bank*), Settings › AI (the three routes), then the personal demo; `GET /health` | **Verified.** `"ok": true`, `demo.ready: true`; every page rendered with the sample books; the test user came back 201 from the public relay. The TrueLayer round trip itself was not repeated (it is recorded as the video's bank feed take: `docs/BANK_FEED_SANDBOX_DEMO.md`) |
| The hosted-model paths on the live server | `evals/runs/live_checks_2026-11-04/report.md` (04:04 UTC, same day): Ask by text on all three routes, Ask by voice with synthetic speech, a scan (classify + read), the Home summary and the goals note, each step's provider from `/ai/calls` | **Verified** (9 AI calls: 7 to the hosted model's API (Contributor tier), 2 to the local open-weights model on our own server; 4 transcriptions by the speech-to-text model; 0 fell back, 0 failed). Not scored: a few live calls are not a measurement |
| HMRC sandbox | `docs/HMRC_SANDBOX_DEMO.md`: the demo's exact call sequence through the public relay, HMRC's real sandbox sign-in, obligations, declaration, submit, receipt (form bundle recorded) | **Verified** once, 05:53 UTC. A signed-in user's own `/vat` card has **not** been run end to end by hand |
| Android | APK 0.3.18+23 installed on the Android emulator: Welcome → *Try the company demo* → Home, Review, Ask, VAT, More › Bank, Settings. The owner ran the app on his own phone the same day (spoken questions to Ask; no log committed). 0.3.19+24 (released 13:20 UTC) adds the Home goals and AI cards, the duplicates card fix and Bank sync; it was built from the same code plus those changes and was **not** re-walked on the emulator | **Two findings**, A1 and A2 below. No phone other than the owner's; sign-in from a Google Play install not tried (the Play listing is in Google's review) |
| Tests | CI on GitHub (`.github/workflows/ci.yml`) green on `8debc2e9`, and on every later `main` commit of the day up to `bbf716ea`; `pytest --collect-only`: runtime 2789, ledger 101, connectors 67, evals 383, relay 181; web e2e about 300 tests in 84 spec files; Flutter about 470 (475 passed locally at 14:55 UK) | **Verified** by CI; the e2e and Flutter counts come from the spec files, not from a run in this audit |
| Secrets | `docs/submission/CHECKLIST.md` section 8, checks 1–3 and 5 on `main` at `8debc2e9` | **Verified**: only the expected hits (`.env.example`; a fake JWT-shaped token in `services/runtime/tests/test_mailboxes.py`; test-mode fake secrets; the LAN address in `.env.example` and the Android network security config). Check 4 (the owner's own real values) is the owner's |
| Provenance | `docs/PROVENANCE.md` commands re-run: 1,727 commits on `main` to `8debc2e9`, no author or committer date before kickoff; 101 reviews in 102 `docs/reviews/*` folders; 1,222 commits with the coding agent's trailer; 156 `claude/*` and 70 `muse/*` merges | **Verified** and written into the page |
| Wording for judges | The public pages and `docs/submission/` grepped for launch, "coming soon", "beta", "early access", "testers", pricing and non-AI model names | **Verified**: the submission build hides the pre-launch wording behind `NEXT_PUBLIC_SUBMISSION_MODE` (`scripts/prelaunch-words.mjs`, `e2e/submission-mode.spec.ts`). Fixed in docs: `docs/submission/VIDEO_SCRIPT.md` was the 28 Oct script (now points at the v3 script); the teaser posts and the X thread had a launch month |
| Docs against the code | README, `how-it-works`, `docs/HONESTY.md`, `docs/PROVENANCE.md`, `docs/BANK_FEED_SANDBOX_DEMO.md`, `docs/submission/*` read against `main` | **Fixed**: every "not yet run end to end" that the day's runs had overtaken (HMRC sandbox, bank feed, Android on a phone, voice, the receipt-crop image model), the 28 Oct test counts, the APK version, the Verifier's state on the live server (the open-weights verifier model off since 2 Nov, so the second reading there is the hosted model checking itself), where the 27 Oct the local open-weights model evals were served |

## Findings

| # | Severity | Finding | State |
|---|---|---|---|
| A1 | High (judges' path) | The Android VAT tab of the company demo opened on *Jan–Mar 2025* with every box at £0.00. Cause: the phone read the `due_period` hint from `GET /books/vat/periods`, which never sent it (only `/books/vat` did, as a map), and fell back to the *oldest* open period; the demo leaves every earlier period open with nothing in it | **Fixed** (`claude/vat-periods-due`): the periods list now carries `due_period` as a period id, so the released 0.3.19 APK opens on Jul–Sep 2026 once the API is deployed, no rebuild needed; the phone's own fallback now picks the latest ended open period and reads a map-shaped hint too (runtime and Flutter tests) |
| A2 | Medium (wording) | The phone's More screen demo card said "nothing is sent to HMRC" while the VAT card files to HMRC's sandbox | **Fixed in code** (same branch): "VAT returns go to HMRC's sandbox, never live HMRC, and no email is sent". Reaches the APK at the next build |
| D1 | Medium (judges' docs) | `docs/submission/VIDEO_SCRIPT.md` was the 28 Oct phone-first script, with a status table saying Android had never run on a phone and several features were not on `main` | **Fixed**: points at `docs/video/SCRIPT_V3.md` and `V3_EDIT.md` (the submitted video) |
| D2 | Medium (judges' docs) | README, `how-it-works`, HONESTY, JUDGING, DESCRIPTION and CHECKLIST still said the HMRC sandbox flow, the bank feed, voice and the phone had not run, and quoted the 28 Oct gates | **Fixed** (this audit's doc commit) |
| D3 | Low | Teaser post texts and the X thread carried "Launching November 2026" and "coming soon" | **Fixed**: waiting-list wording; the public teaser cut is marked as not used for the hackathon |
| D4 | Low | `docs/submission/DESCRIPTION.md`'s 150-word text is 154 words and the 400-word text 420 after the refresh | **Open**: trim on the form if its counter objects |
| M1 | Low (honesty) | On the live server the Verifier is the hosted model checking itself (the open-weights verifier model off since 2 Nov), less independent than the measured the open-weights verifier model | **Documented** in `how-it-works`, HONESTY and META_MODELS; not changed |
| M2 | Low | `GET /ai/calls` keeps only the last 50 calls in memory, so the call records OPEN_WEIGHTS.md quotes have rolled off | **Documented**: the *Reproduce it* commands make fresh ones; the longer record is the live-checks report |

## Not verified in this audit

- A signed-in user's own books against a real OneDrive (every feature beyond the owner's 26–27 Oct hand runs is tested on
  fakes), a real mailbox or calendar; *Load sample books* on a real account.
- The Android app on any phone but the owner's; sign-in from a Play install; the 0.3.19 build on the emulator.
- TrueLayer token refresh and `POST /connections/extend`; a real bank's sandbox.
- The web e2e suite and the Flutter suite were not re-run by the audit itself (CI ran them on every push; Flutter was
  run locally once for the A1/A2 fix).
- The hosted model's API's remaining credit for the judging week (owner's dashboard).

## What the owner still does (from `docs/submission/CHECKLIST.md`)

Watch the final video once end to end; upload it unlisted and test it signed out; fill the form by 18:00 UK; confirm the
The hosted model's API credit; keep the server up through judging; after the hackathon rotate the API key for the hosted model.
