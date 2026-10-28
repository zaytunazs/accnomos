# Review: bank-line AI prompt and built-in Travel/Subsistence/Motor codings (`muse/bank-ai-travel`)

Reviewed by the integrator on 28 Oct 2026 before merging (the branch came without a review). Three commits: the Bank
page's AI prompt names Travel, Subsistence and Motor for fares, meals and fuel; four built-in codings; tests.

## What it does

- `app/bank_reconcile.BANK_SUGGEST_PROMPT` adds three sentences: rail, bus, underground, taxi, flights and hotels are
  7400 Travel; cafes and meals while working away are 7410 Subsistence; fuel is 7300 Motor expenses, never Travel.
  Generic words only; a test checks that no supplier name (Pret, Greggs, Trainline, Shell…) is in the prompt.
- `app/bank_rules.BUILTIN_RULES`: four rules (`trainline|\btfl\b` and `parking` → 7400 Travel; `petrol|diesel|\bfuel\b`
  → 7300 Motor expenses; `caf[eé]|restaurant|sandwich` → 7410 Subsistence), money out only.

## Checked

- **Built-ins sit behind the user's rules.** `suggest_rule` runs `first_match` over the user's saved rules first and
  only falls back to `BUILTIN_RULES` when none matches (`test_suggest_rule_prefers_the_users_rule`,
  `test_suggest_rule_falls_back_to_builtins`). They are not written to `_System/bank_rules.json`, so the user's rule
  order and the Rules page are unchanged.
- **Suggestions only.** The only caller that turns a rule suggestion into an entry is the accept path
  (`kind == "rule"`), i.e. the user's tap on the Bank page; nothing posts a built-in coding automatically.
- **VAT.** A built-in sets no VAT code, so the coding claims no VAT (`_split_gross`): the safe direction for a bank line
  with no receipt (rail and TfL fares are zero-rated anyway); the user can add VAT in Review.
- **No false hits on the tested words** (`SCREWFIX`, `OUTFLANK`, `VODAFONE`, `HMRC VAT`) and none on money in.
- The three accounts exist in the chart (`app/journal.py` category map).

## What remains

- The regexes are deliberately small; `\bfuel\b` will also catch e.g. a "FUEL CARD" settlement that is not fuel.
- No eval run measures the effect of the prompt change on the bank-matching eval (`evals/runs/bank_matching`).
