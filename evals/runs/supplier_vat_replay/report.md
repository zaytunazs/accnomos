# Replay: the supplier-aware VAT-number check (27 Oct 2026)

Owner's rule: for a VAT-registered business, a purchase over £250 that charges no VAT and shows no VAT number is flagged
(`SUPPLIER_VAT_UNKNOWN`, "Is <supplier> VAT-registered? Over £250 they should give a VAT invoice") only while the books
don't know the supplier; once the user has ticked "isn't VAT-registered", or a VAT number has been seen, the check decides
on its own. The eval has no books, so every supplier is unknown here.

## Perfect readings (the gold fields), 200 documents

    cd evals && python -m harness.replay --gold --show

| | before (`5eb96b0`) | after |
|---|---:|---:|
| status matches gold | 193 | 197 |
| false passes (proposed, gold expects *Needs a look*) | 6: 005, 016, 027, 038, 049, 060 | **2**: 038, 060 |
| false alarms (*Needs a look*, gold expects proposed) | 1: 057 | 1: 057 |

- 005, 016, 027, 049 (`no_vat_number`, £270–£368.50, no VAT, no VAT number) now reach *Needs a look* with the question.
- 038 and 060 are the same case under £250. The owner's rule passes them ("under £250 with zero VAT: OK as today"); the
  older 001-060 gold rule expects *Needs a look* for every `no_vat_number` document. Left as a known disagreement.
- 057 (`GB 99887766`, malformed VAT number) is unchanged: the gold says proposed, the format check fails it (the demo seed
  relies on that).
- 176 and 184 (`edge_foreign_gbp`, German SaaS suppliers charged in GBP, £843.45 and £310.31, no VAT, no VAT number) are
  flagged by the new rule. Their gold `expected_status` was changed from `proposed` to `needs_a_look` with this change
  (the "before" column is scored against the new gold; against the old gold, before had 194 matches and 0 alarms on them).
  The reading has no supplier address, so code can't tell an overseas supplier from a UK one.

## The stored Glimmer readings (`runs/glimmer_messy_200`): not re-run

The per-document records of that run are kept locally only (`.gitignore`) and were not in the checkout this change was
made in, so `python -m harness.replay runs/glimmer_messy_200` could not be run. Last measured (extraction-quality-2
review): false passes 9 before the repairs, 11 after, of which 005, 027 and 049 are the zero-VAT, no-VAT-number receipts
over £250.

What can be said without the records: with no books the new check only ever adds a fail (VAT charged with no number fails
exactly as before; zero VAT over £250 from an unknown supplier now fails too), so no stored reading can move from
*Needs a look* to proposed. The false-pass count therefore cannot rise, except through 176/184 whose gold changed to
`needs_a_look`: they would count as false passes only if their stored readings are proposed for another reason (a VAT
number or VAT the documents don't print, or a total at or under £250). Expected: 11 → 8 if the stored readings of 005,
027 and 049 carry no VAT, no VAT number and their printed totals. **Run the replay on the machine that has the records
to confirm.**
