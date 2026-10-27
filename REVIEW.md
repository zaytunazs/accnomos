# Review: `claude/supplier-vat-memory`

Second-agent review of the supplier-aware VAT-number check (brief: `TASK_BRIEF.md`), 27 Oct 2026.

## What was checked

- `pytest -q`: `services/runtime` 811 passed, 1 skipped (809 before this review's tests); `evals` 158; `packages/ledger` 35;
  `packages/connectors` 43; `services/hmrc-relay` 102.
- `apps/web`: `pnpm run build` passes; Playwright `review.spec.ts`, `contacts.spec.ts`, `settings.spec.ts`: 15/15 pass
  (`review.spec.ts` re-run after the toast fix, 9/9).
- `cd evals && python -m harness.replay --gold --show` reproduces the report: status 197/200, false passes 2 (038, 060),
  false alarm 1 (057).
- Read the whole diff against the brief's rule table. `check_vat_number_required` applies the rules in the brief's order:
  VRN shown → OK; business not VAT-registered → OK; VAT charged with no VRN → fail (quoting the known VRN for a registered
  supplier); `not_registered` with zero VAT → OK; `unknown`, zero VAT, over £250, a purchase → `SUPPLIER_VAT_UNKNOWN` with the
  question; anything else → OK. Supplier status lives only in `_System/Contacts/contacts.json` (plus an audit line). Nothing
  is written server-side. The tick is validated at the boundary: a bool only, refused on a sales invoice, when a VRN is shown, or when
  VAT is charged; the route turns that into a 400. A broken contacts or profile file degrades to "unknown supplier / registered
  business" and never blocks a scan or an approval. Money is unchanged: the check reads totals and never rounds or writes them.
- Seed: `test_seed_demo.py` was changed. Supplier contacts go from 13 to 14 (Hargreaves & Son Hardware is created by the up-front
  `not_registered` mark), and `tools/seed_demo.md` was updated to match. Posted counts and VAT figures are unchanged.
- Mobile: no Flutter toolchain here. Checked by hand that `_warnBg/_warnBorder/_warnInk` and `RuntimeClient.approve(edits:)`
  exist and the tick is only sent when the card asks.
- `/extract` (stateless upload, no books) still treats every supplier as unknown. That is correct, since it has no contacts to look in.

## What I fixed

- `fdb44f4`: tests the brief asked for that were missing: lookup by **alias** after a rename, and the tick through the HTTP
  approve route (400 on a VAT-charging receipt and on a non-bool, 200 + `not_registered` stored otherwise).
- `ca2882b`: web Review toast left out "… remembered as not VAT-registered" when "Always do this" was also ticked.
- `e39d795`: `docs/HONESTY.md` header test counts and what was re-run were stale (642 runtime tests, "web not rebuilt").

## What remains

- **Undo does not forget a tick.** Undoing an approval reopens the card, but the supplier stays `not_registered` in
  contacts.json, so later receipts from them pass without asking. The user has to reset it on Contacts. The same applies to `registered`
  learnt from a VRN.
- **Stored Glimmer replay not re-run.** The per-document records of `evals/runs/glimmer_messy_200` are git-ignored and are not
  in this checkout either. The report's expected 11 → 8 false passes is unconfirmed: run `python -m harness.replay
  runs/glimmer_messy_200` where the records are.
- **Gold 176/184 were changed** from `proposed` to `needs_a_look` to fit the new rule (overseas SaaS, over £250, no VAT). This is
  documented in `evals/gold/README.md` and the replay report. Against the old gold the new code has 3 false alarms, not 1.
- **038 and 060** (under £250, no VAT, no VRN) are still false passes against the older 001–060 gold rule. The owner's rule passes them on purpose.
- **Flutter** change (tick, model, `proposal_editing_test.dart`) was not analysed, built or tested.
- Within one inbox scan the contacts are read once, so a status learnt by an Autopilot approval mid-scan applies from the
  next scan.
- Scan-time lookup reads saved `contacts.json` only. A supplier whose VRN is only in the ledger counts as unknown until
  *Refresh from books* (already in HONESTY).
- `TASK_BRIEF.md` is committed at the repo root (`089cd80`). Drop it before merging if briefs shouldn't land on `main`.

## How to verify by hand

Start the runtime and web app in test mode and sign in with the fake account. Drop a receipt over £250 with no VAT and no VAT
number from a new supplier (e.g. gold `005_no_vat_number`) into `00 Inbox` and scan. It lands in *Needs a look* reading
"Is Hargreaves & Sons Ironmongery VAT-registered? Over £250 they should give a VAT invoice", with a tick
"… isn't VAT-registered". Tick it and approve. The toast says the supplier was remembered, and Contacts shows
"Not VAT-registered" for them. Scan a second such receipt from the same supplier (another spelling is fine): it is
*proposed* without the question. On Contacts set the status back to "Not known: ask me over £250" and the next receipt asks again.
In Settings › Business, untick "This business is VAT-registered" (only possible with no VAT number). No receipt is then
questioned for a missing VAT number.
