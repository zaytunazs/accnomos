# Property documents eval

Model `muse-glimmer:30b` at `http://localhost:11434`; 2026-10-28T13:46:14+00:00. Code under test: `app.ai.extract.extract_document` (the generic reader).

There is no property-specific reader in the app (`services/runtime/app/property.py` works out every figure in code from approved entries; nothing in `app/ai/` reads letting paperwork). This eval scores the existing generic extraction reader (`app.ai.extract.extract_document`) on the landlord documents: category, property, amount and date, as below.

- Documents: **108** (108 answered, **0 refusals**, 0.0%)
- Fully exact (category, property, amount and date all right): **1.9%** of all documents (a refusal counts as wrong)
- Latency: mean 19.676 s, p50 21.134 s, p95 24.518 s, max 27.191 s (total 2125.0 s)

## Per-field accuracy (answered documents)

| Field | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| category | 108 | 26 | 24.1% |
| property | 108 | 8 | 7.4% |
| amount | 108 | 34 | 31.5% |
| date | 108 | 108 | 100.0% |

## Per-kind accuracy (refusals count as wrong)

| Kind | Docs | Answered | Fully exact | Accuracy |
|---|---:|---:|---:|---:|
| insurance | 6 | 6 | 1 | 16.7% |
| invoice | 24 | 24 | 1 | 4.2% |
| letting_statement | 72 | 72 | 0 | 0.0% |
| mortgage_statement | 6 | 6 | 0 | 0.0% |

## Worst 10 misses

| Id | Kind | Wrong fields | Got | Want |
|---|---|---|---|---|
| landlord_10/2026-04_flat | letting_statement | amount, category, property | category=Sundry amount=1250.6 date=2026-04-28 | category in ['Sales'] amount=624.8 date=2026-04-28 property=flat |
| landlord_10/2026-04_house | letting_statement | amount, category, property | category=Sundry amount=2988.8 date=2026-04-28 | category in ['Sales'] amount=994.4 date=2026-04-28 property=house |
| landlord_10/2026-05_flat | letting_statement | amount, category, property | category=Sundry amount=1249.6 date=2026-05-28 | category in ['Sales'] amount=624.8 date=2026-05-28 property=flat |
| landlord_10/2026-05_house | letting_statement | amount, category, property | category=Sundry amount=2988.8 date=2026-05-28 | category in ['Sales'] amount=994.4 date=2026-05-28 property=house |
| landlord_10/2026-06_flat | letting_statement | amount, category, property | category=Sundry amount=1249.6 date=2026-06-28 | category in ['Sales'] amount=624.8 date=2026-06-28 property=flat |
| landlord_10/2026-06_house | letting_statement | amount, category, property | category=Sundry amount=2988.8 date=2026-06-28 | category in ['Sales'] amount=994.4 date=2026-06-28 property=house |
| landlord_10/2026-07_flat | letting_statement | amount, category, property | category=Sundry amount=1249.6 date=2026-07-28 | category in ['Sales'] amount=624.8 date=2026-07-28 property=flat |
| landlord_10/2026-07_house | letting_statement | amount, category, property | category=Sundry amount=1678.82 date=2026-07-28 | category in ['Sales'] amount=839.41 date=2026-07-28 property=house |
| landlord_10/2026-08_flat | letting_statement | amount, category, property | category=Sundry amount=1249.6 date=2026-08-28 | category in ['Sales'] amount=624.8 date=2026-08-28 property=flat |
| landlord_10/2026-08_house | letting_statement | amount, category, property | category=Sundry amount=2988.8 date=2026-08-28 | category in ['Sales'] amount=994.4 date=2026-08-28 property=house |

Refusals (the model gave nothing usable):


How it is scored: category against harness-chosen defensible generic categories (the generic schema has no landlord categories); property by the expected address tokens surviving anywhere in the model's JSON (the schema has no property field); amount within a penny of the headline total (payout for statements; printed Total, largest `of which` line, or sum of positives for bills); date exactly.
