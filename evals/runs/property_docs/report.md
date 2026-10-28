# Property documents eval

Model `muse-glimmer:30b` at `http://localhost:11434`; 2026-10-28T17:31:52+00:00. Code under test: `app.ai.property_read.read_property_document` + `app.property_readings.from_reading` (pounds to pence, the property matched by code, the lines checked against the printed totals). The generic extraction reader runs on every document as a baseline column.

- Documents: **108** (108 answered, **0 refusals**, 0.0%)
- Fully exact (kind, property and every line's category and amount right): **89.8%** of all documents (a refusal counts as wrong); generic baseline **0.9%**
- Latency: mean 37.113 s, p50 40.678 s, p95 46.32 s, max 50.513 s (total 4008.2 s)

## Per-field accuracy (answered documents; line fields score every gold figure)

| Field | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| kind | 108 | 108 | 100.0% |
| property | 108 | 108 | 100.0% |
| line_category | 186 | 186 | 100.0% |
| line_amount | 186 | 175 | 94.1% |

## Per-kind accuracy (refusals count as wrong; baseline is the generic reader's fully-exact share)

| Kind | Docs | Answered | Fully exact | Accuracy | Baseline exact | Baseline |
|---|---:|---:|---:|---:|---:|---:|
| insurance | 6 | 6 | 6 | 100.0% | 0 | 0.0% |
| invoice | 24 | 24 | 13 | 54.2% | 1 | 4.2% |
| letting_statement | 72 | 72 | 72 | 100.0% | 0 | 0.0% |
| mortgage_statement | 6 | 6 | 6 | 100.0% | 0 | 0.0% |

## Generic baseline per field (answered baseline documents)

| Field | Scored | Correct | Accuracy |
|---|---:|---:|---:|
| category | 108 | 26 | 24.1% |
| property | 108 | 7 | 6.5% |
| amount | 108 | 34 | 31.5% |
| date | 108 | 108 | 100.0% |

## Worst 10 misses

| Id | Kind | Wrong fields | Got | Want |
|---|---|---|---|---|
| landlord_10/17_invoice | invoice | amt:domestic_items | figures={'domestic_items': 510.99} property=flat | figures={'domestic_items': 505.99} property=flat |
| landlord_11/16_invoice | invoice | amt:repairs | figures={'repairs': 296.1} property=house | figures={'repairs': 253.8} property=house |
| landlord_11/17_invoice | invoice | amt:domestic_items | figures={'domestic_items': 377.99} property=flat | figures={'domestic_items': 372.99} property=flat |
| landlord_12/16_invoice | invoice | amt:repairs | figures={'repairs': 423.5} property=house | figures={'repairs': 363.0} property=house |
| landlord_12/17_invoice | invoice | amt:domestic_items | figures={'domestic_items': 505.99} property=flat | figures={'domestic_items': 525.99} property=flat |
| landlord_7/16_invoice | invoice | amt:repairs | figures={'repairs': 268.1} property=house | figures={'repairs': 229.8} property=house |
| landlord_7/17_invoice | invoice | amt:domestic_items | figures={'domestic_items': 387.99} property=flat | figures={'domestic_items': 407.99} property=flat |
| landlord_8/16_invoice | invoice | amt:repairs | figures={'repairs': 419.3} property=house | figures={'repairs': 359.4} property=house |
| landlord_8/17_invoice | invoice | amt:domestic_items | figures={'domestic_items': 544.99} property=flat | figures={'domestic_items': 564.99} property=flat |
| landlord_9/16_invoice | invoice | amt:repairs | figures={'repairs': 503.3} property=house | figures={'repairs': 431.4} property=house |

Refusals (the model gave nothing usable):


How it is scored: kind against the gold kind; property by the code match against the two registered properties (never an invented id); each gold figure by its category on a posted line (headlines and repaid capital excluded) adding up within a penny. The baseline runs the generic reader with its old rules: category against defensible generic categories, property by address tokens anywhere in its JSON, amount within a penny of the headline total, date exactly.
