# Property documents eval

Model `muse-glimmer:30b` at `http://localhost:11434`; 2026-10-28T16:24:26+00:00. Code under test: `app.ai.property_read.read_property_document` + `app.property_readings.from_reading` (pounds to pence, the property matched by code, the lines checked against the printed totals). The generic extraction reader runs on every document as a baseline column.

- Documents: **108** (108 answered, **0 refusals**, 0.0%)
- Fully exact (kind, property and every line's category and amount right): **82.4%** of all documents (a refusal counts as wrong); generic baseline **1.9%**
- Latency: mean 37.697 s, p50 40.98 s, p95 47.141 s, max 50.073 s (total 4071.2 s)

## Per-field accuracy (answered documents; line fields score every gold figure)

| Field | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| kind | 108 | 108 | 100.0% |
| property | 108 | 108 | 100.0% |
| line_category | 186 | 174 | 93.5% |
| line_amount | 186 | 167 | 89.8% |

## Per-kind accuracy (refusals count as wrong; baseline is the generic reader's fully-exact share)

| Kind | Docs | Answered | Fully exact | Accuracy | Baseline exact | Baseline |
|---|---:|---:|---:|---:|---:|---:|
| insurance | 6 | 6 | 0 | 0.0% | 1 | 16.7% |
| invoice | 24 | 24 | 17 | 70.8% | 1 | 4.2% |
| letting_statement | 72 | 72 | 72 | 100.0% | 0 | 0.0% |
| mortgage_statement | 6 | 6 | 0 | 0.0% | 0 | 0.0% |

## Generic baseline per field (answered baseline documents)

| Field | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| category | 108 | 28 | 25.9% |
| property | 108 | 8 | 7.4% |
| amount | 108 | 34 | 31.5% |
| date | 108 | 108 | 100.0% |

## Worst 10 misses

| Id | Kind | Wrong fields | Got | Want |
|---|---|---|---|---|
| landlord_10/13_insurance | insurance | amt:premises, cat:premises | figures={'premises': 0.0} property=house | figures={'premises': 285.0} property=house |
| landlord_10/14_mortgage_statement | mortgage_statement | amt:finance_res, cat:finance_res | figures={'finance_res': 0.0} property=house | figures={'finance_res': 2840.88} property=house |
| landlord_11/13_insurance | insurance | amt:premises, cat:premises | figures={'premises': 0.0} property=house | figures={'premises': 414.5} property=house |
| landlord_11/14_mortgage_statement | mortgage_statement | amt:finance_res, cat:finance_res | figures={'finance_res': 0.0} property=house | figures={'finance_res': 2851.14} property=house |
| landlord_12/13_insurance | insurance | amt:premises, cat:premises | figures={'premises': 0.0} property=house | figures={'premises': 360.75} property=house |
| landlord_12/14_mortgage_statement | mortgage_statement | amt:finance_res, cat:finance_res | figures={'finance_res': 0.0} property=house | figures={'finance_res': 2720.34} property=house |
| landlord_7/13_insurance | insurance | amt:premises, cat:premises | figures={'premises': 0.0} property=house | figures={'premises': 224.25} property=house |
| landlord_7/14_mortgage_statement | mortgage_statement | amt:finance_res, cat:finance_res | figures={'finance_res': 0.0} property=house | figures={'finance_res': 2341.92} property=house |
| landlord_8/13_insurance | insurance | amt:premises, cat:premises | figures={'premises': 0.0} property=house | figures={'premises': 355.0} property=house |
| landlord_8/14_mortgage_statement | mortgage_statement | amt:finance_res, cat:finance_res | figures={'finance_res': 0.0} property=house | figures={'finance_res': 2366.54} property=house |

Refusals (the model gave nothing usable):


How it is scored: kind against the gold kind; property by the code match against the two registered properties (never an invented id); each gold figure by its category on a posted line (headlines and repaid capital excluded) adding up within a penny. The baseline runs the generic reader with its old rules: category against defensible generic categories, property by address tokens anywhere in its JSON, amount within a penny of the headline total, date exactly.
