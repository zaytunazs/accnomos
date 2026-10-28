# Property docs eval misses: insurance, mortgage statements, invoices

Run: `evals/runs/property_docs` on Muse Glimmer, 108 gold documents.
Headline: 82.4% all fields exact; letting statements 72/72, invoices 17/24,
insurance 0/6, mortgage statements 0/6. Line category 93.5%, line amount 89.8%.

The raw per-line model output was not retained in `results.jsonl` (only the
scored figures, checks and problems), so flag-vs-category is separated below
only where the stored checks distinguish it. The gold files are right in every
case: each was re-derived from `evals/gold/gen_gold_landlord.py` and HMRC
replacement relief (cost + disposal − proceeds).

## Insurance (6/6 miss; posted `premises` £0.00 on every one)

Gold: two lines, `Annual premium including Insurance Premium Tax` (£224.25–
£414.50) and `of which Insurance Premium Tax` (£24.02–£44.41); the figure is
the full premium (IPT included, not reclaimable; the generator works it as
`ins * 12 // 112`).

| Id | Got | Want | Checks |
|---|---|---|---|
| landlord_7/13_insurance | £0.00 | £224.25 | LINES_SUM False |
| landlord_8/13_insurance | £0.00 | £355.00 | LINES_SUM False |
| landlord_9/13_insurance | £0.00 | £285.25 | LINES_SUM False |
| landlord_10/13_insurance | £0.00 | £285.00 | LINES_SUM False |
| landlord_11/13_insurance | £0.00 | £414.50 | LINES_SUM False |
| landlord_12/13_insurance | £0.00 | £360.75 | LINES_SUM True |

Cause: **prompt wording** (reader). The `info` flag sentence offers two
patterns that both match this document: the IPT line is `of which` (info), but
the premium line itself reads as "a printed Total when the parts are listed"
(info). On five documents the model marked the premium as info too, so no
posted `premises` line remained and LINES_SUM failed on an empty sum.
landlord_12 differs (LINES_SUM passed with nothing posted to `premises`), so
there the premium stayed non-info but took a wrong category. Either way the
model never had a per-kind rule saying the premium is the one expense line.
Scorer and gold are correct: the figure is the premium including IPT, and
excluding `info` lines is right. The code check is too weak: nothing flags
"an insurance reading with no posted insurance line".

## Mortgage statements (6/6 miss; posted `finance_res` £0.00 on every one)

Gold: a `Monthly payments made (6)` headline plus the split `of which
interest` / `of which capital repaid`; the figure is interest only
(£1,941.50–£2,851.14), capital is not a cost. All six rows show
LINES_SUM False and MORTGAGE_SPLIT False with no problems recorded.

Cause: **prompt wording** (reader). The same `info` sentence names "an `of
which` line" as the example of info, so the model marks the `of which
interest` / `of which capital` split lines as info (or drops the split), while
the payments-made headline is also info by the same sentence. Nothing posted
remains, hence £0.00 and both checks failing. The prompt never states the
intended shape: headline info, interest posted as `finance_res`, capital
flagged `capital`. The code check cannot repair this, and there is no fee arm:
any extra fee line would fall outside `interest + capital = total`, so the
check as written also rejects statements with fees. Scorer and gold are
correct.

## Invoices (7/24 miss)

### VAT folded into the figure (1): scorer wrong

landlord_10/16_invoice (boiler repair): got `repairs` £149.00, want £178.80;
LINES_SUM True. The model did the desired thing: net £149.00 on the line with
the £29.80 VAT kept separate (the `vat` field), not folded into the amount.
`score_figures` sums only `amount_pence` and ignores the schema's `vat`
field, so it compared net against the gross gold figure (£149.00 + £29.80 VAT;
the landlord is not VAT registered, so the figure is correctly gross). The
other five boiler repairs passed only because the model happened to emit
gross amounts there. Cause: **scorer wrong**; the reader behaviour is the one
this pass standardises on.

### Replacement washing machine (6): model drops lines

| Id | Got | Want | Missing |
|---|---|---|---|
| landlord_7/17_invoice | £387.99 | £407.99 | £20.00 disposal |
| landlord_8/17_invoice | £544.99 | £564.99 | £20.00 disposal |
| landlord_9/17_invoice | £462.99 | £482.99 | £20.00 disposal |
| landlord_10/17_invoice | £510.99 | £505.99 | £20.00 disposal, −£25.00 trade-in |
| landlord_11/17_invoice | £377.99 | £372.99 | £20.00 disposal, −£25.00 trade-in |
| landlord_12/17_invoice | £505.99 | £525.99 | £20.00 disposal |

Every one is short by exactly disposal minus trade-in: the model emitted the
machine line only and dropped `Removal and disposal of the old machine` and
`Trade-in allowance` (including the £0.00 ones). No headline total is printed
on these documents (`No headline total read`, no LINES_SUM check), so nothing
caught the omission. Cause: **model output**; the prompt says "every money
line" but £0.00 and minus/allowance lines still get skipped. Gold is right
(relief = cost + disposal − proceeds, as in the generator). Scorer is right.

## What changes in the second pass

1. Prompt: per-kind `info`/`capital` rules (premium is the expense line, only
   the IPT breakdown is info; payments-made headline is info, the interest and
   capital split lines are not; Total is info only when the parts are listed;
   VAT shown separately goes in `vat`, never folded into `amount`; every
   printed amount gets its own line, including £0.00 and minus lines).
2. Code checks: insurance yields exactly one posted insurance line equal to
   the premium; mortgage checks interest + capital + fees = payment;
   LINES_SUM counts `vat` alongside `amount` so VAT-separate invoices add up.
3. Scorer: `score_figures` adds each posted line's `vat` to its amount (the
   one scorer fix; everything else it does stays).
