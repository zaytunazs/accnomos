# Review: `claude/submission-refresh` (27 Oct 2026)

Scope: `docs/submission/*` only. `README.md`, `docs/HONESTY.md` and `docs/REMAINING.md` were read as the source of truth and not edited.
Sources read: README, HONESTY, REMAINING, DEMO, the reviews that exist (part-payments, payments-2, gold-ledger2, autopilot-eval, reports, audit-trail, intake-formats, robustness), `evals/runs/*/report.md`, `git log`. There is no `docs/reviews/bank-rules` or `loose-ends-2` directory in this checkout; bank rules were taken from the README row and `docs/reviews/bank-ui`.

## What changed per file

- `CHECKLIST.md`: ticked Entra Android entry (27 Oct), `flutter analyze`/`test` (158), 0.3.2+5, server keys (`ACTIONS_SIGNING_KEY`, HMRC sandbox, `BASETEN_API_KEY`) and the Spark Open verifier wiring, each with a "glance" check because the repo records none of them. Kept owner-only: Play production status, real-phone sign-in, demo accounts, the HMRC sandbox submission run (connected once, no end-to-end run recorded), the `META_API_KEY` decision, video, the secrets check, form entries. Added "keep the DGX Spark on through judging", waiting for the Spark Open eval, and a note that README/HONESTY/DEMO test counts need syncing after their branches merge. Section 7 (secrets check) kept verbatim except the branch name.
- `DESCRIPTION.md`: both versions rewritten for the current feature set, the Meta model story and the Autopilot numbers with their caveat (17 false posts in 467, all re-dated copies; 0 of 154 clean). Header explains what not to shorten and where the Spark Open sentence goes.
- `META_MODELS.md`: now one table (model, where it runs, what it does, status, evidence) plus short notes on limits; the Spark Open row carries the placeholder.
- `VIDEO_SCRIPT.md`: 3:00 script re-timed to add payments and credit notes, bank rules and reconcile, reports and audit trail, and an Autopilot-eval card; those shots (and any not run live) are marked "film only if checked" and have no still, because the dry-run stills predate them. Spark Open and Android guidance updated; shot list extended.
- `JUDGING.md`: criteria mapped to current evidence paths; test counts from the owner's 27 Oct figures; honesty section lists the evals' own failures. The "run it in 10 minutes" section is unchanged.

## Word counts (whitespace-separated, between the rules in `DESCRIPTION.md`)

- 150-word version: **149**. 400-word version: **399**. The form's counter may differ.

## Open placeholders and unverified items

- `[pending: evals/runs/spark_open_200]` in `META_MODELS.md` (status cell and evidence cell) and `JUDGING.md` (Meta models, two-model design row). `DESCRIPTION.md` has no placeholder; its header says where to add one sentence once the numbers exist.
- Facts taken from the owner's 27 Oct message and not checkable in the repo: Entra Android entry, server keys set, Play build 1 in review, Baseten model id listing and the 7 s call, Android 158 tests, main test counts (1,176 / 258 / 102 / 195 / 158). `docs/HONESTY.md` still says the Entra step is pending and quotes 148 Flutter and 970 runtime tests; `README.md` and `docs/DEMO.md` also lag. After those branches merge, check the submission files still agree with them.
- `README.md` mentions Reports/Audit on Android; `docs/HONESTY.md` says a read-only audit list exists in More. The script's Reports/Audit shot is web.
- `docs/META_MODELS.md` (not in scope) still calls the Spark Open slug unconfirmed; `docs/submission/META_MODELS.md` follows `verify.py` and HONESTY.md, which say it is confirmed.
- New video shots have never been run on a real account: payments and credit notes, bank rules and reconcile, reports, audit trail. The HMRC submission has not been run end to end. Nothing was pushed; `.v` was not added.
