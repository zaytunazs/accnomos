# Task: Supplier-aware VAT-number check — the books remember whether each supplier should carry a VAT number

Accnomos monorepo (public; UK English; no secrets). **Owner's rule (27 Oct):** if the user's business is VAT-registered, a receipt
over £250 with no VAT number is flagged for a look **only when the supplier is not yet known**; once a supplier is in the books the
system knows whether that supplier should or shouldn't show a VAT number, and decides without asking again.
Read first `services/runtime/app/checks.py` (`check_vat_number_required`), `app/pipeline.py` (checks run on `ExtractedDoc` with no
books access today), `app/contacts.py` (`Contact.vrn`, `source`, `aliases`, normalised keys), `app/approve.py` (where a supplier's
approved history could be recorded), `app/schemas.py`, the business profile (VRN setting: `X-Business-Name`/VAT settings — find where
the user's own VRN is stored; if nowhere, add `vat_registered: bool` to the invoice/business profile and the web Settings › Business),
`tools/seed_demo.py` + `services/runtime/tests/test_seed_demo.py` (the demo plan pins counts and VAT figures), `docs/reviews/extraction-quality-2/REVIEW.md`
("What remains": gold 005/016/027/049 are over £250, no VAT, no VRN), `evals/gold/README.md`.

## Deliverables
1. **Supplier memory**: on approve, the supplier's contact gains `vat_status`: `registered` (a VRN was seen or entered), `not_registered`
   (user approved a zero-VAT receipt with no VRN and ticked "this supplier isn't VAT-registered" — add that tick to the approve edits,
   web + Android), or `unknown`. Stored in `_System/Contacts/contacts.json` only.
2. **The check** becomes supplier-aware: the pipeline passes a `SupplierKnowledge` (looked up by normalised supplier name/alias) into
   `run_checks`. Rules, in order: VRN on the receipt → OK (and learn `registered`). Business not VAT-registered → never flag. Supplier
   `registered` but no VRN on the receipt and VAT charged → fail ("their VAT number is usually …; can't reclaim without it"). Supplier
   `not_registered` and zero VAT → OK. Supplier `unknown`, zero VAT, over £250 → **needs a look** with the question on the card
   ("Is <supplier> VAT-registered? Over £250 they should give a VAT invoice"). Under £250 with zero VAT → OK as today.
3. **Cards**: web Review and Android Review show the question and the tick; approving with the tick records `not_registered`; the
   Contacts page shows and lets the user edit `vat_status`.
4. **Gold and seed**: 005/016/027/049 stay `needs_a_look` for an unknown supplier; the demo seed marks those suppliers' contacts
   `not_registered` *before* the inbox scan where the plan needs them posted, so the pinned demo counts and VAT figures do not change
   (verify `test_seed_demo.py` is untouched or the doc numbers are updated together). Replay numbers in `evals/runs/` and
   `docs/HONESTY.md` updated (the false-pass count must not rise).
5. Tests for every rule; `pytest`, `pnpm run build`, e2e `review.spec.ts`; Flutter change kept to the tick + model (analyser not available here).
Commit in small steps; do not push. Finish with `git log --oneline -8` and the rule table as implemented.
