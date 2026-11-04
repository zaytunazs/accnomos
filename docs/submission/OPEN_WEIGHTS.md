# Meta open-weight models in Accnomos: where they run and what they do

Accnomos calls only Meta models at run time. Two of them are Meta open weights.

## Muse Glimmer 30B

- **Where it runs:** our own GPU server in the owner's office (`muse-glimmer:30b` behind a local model server). It sits in the live server's provider chain as `spark`; `GET https://api.accnomos.com/health` lists it as `{"name": "spark", "model": "muse-glimmer:30b", "configured": true}`. In local mode it can also run on the user's own computer instead.
- **What it does:**
  - **Fallback:** it takes over when the Meta Model API is down. The circuit breaker, timeouts and failover are in `services/runtime/app/ai/chain.py`.
  - **Local model first:** this is a choice in Settings › AI. Glimmer reads documents, categorises and answers first. When its reply does not come back in a usable form, the same request goes to the Meta Model API, so most calls spend no Meta credit and stay off the Meta API (`apply_route` in `services/runtime/app/ai/config.py`, `accept` in `chain.run`).
  - **Local model only:** nothing goes to the Meta Model API. The setting lists its limitations next to it: it is slower, weaker on messy photos, has no voice input and has no fallback.
  - **Tasks:** receipt and invoice reading (vision), categorising, Ask answers, the Home summary, goal notes, duplicate judgements and the verifier's second reading.
- **Measured:** on 200 clean and 200 messy synthetic documents, with code repairs, a re-read and the verifier on, it got all fields right on 85 % of clean and 80 % of messy documents, and the sale/purchase side right on 100 % of both (`evals/runs/glimmer_200_v2`, `evals/runs/glimmer_messy_200_v2`). On the 40-question Ask eval its figures were exact 32/32 with 0 timeouts (`evals/runs/ask_40/report.md`). The autopilot safety eval made 0 false posts on 154 clean documents with the verifier on (`evals/runs/autopilot_l2/report.md`).

## Muse Spark Open

- **Where it runs:** a partner inference host (hosted open weights). It is switched off on the live server since 2 Nov 2026.
- **What it did:** it was the independent verifier and reader in the extraction evals. It got all fields right on 91 % of clean and 93 % of messy documents (`evals/runs/spark_open_200`, `evals/runs/spark_open_messy_200`).

## Live call records (provenance)

The server keeps the last 50 AI calls in memory, without their content: `GET https://api.accnomos.com/ai/calls`.

Two questions were asked on the live server on 4 Nov 2026 at 03:29 UTC. Both were "How much VAT do I owe this quarter?", against the fictional company demo (`POST /books/ask` with `X-Demo-Session`). The only difference was the route header:

| `X-AI-Route` | Served by | Model | Latency | Fell back |
|---|---|---|---|---|
| `local_only` | `spark` (our own GPU server) | `muse-glimmer:30b` | 4.5 s | no |
| `meta_first` | `meta` (Meta Model API) | `muse-spark-1.3-contributor` | 3.7 s | no |

The raw records, exactly as `/ai/calls` returned them:

```json
[
 {"at": "2026-11-04T03:29:31.840839Z", "task": "ask_answer", "provider": "meta",
  "model": "muse-spark-1.3-contributor", "latency_ms": 3674, "ok": true, "fell_back_from": [], "error": null},
 {"at": "2026-11-04T03:29:26.970604Z", "task": "ask_answer", "provider": "spark",
  "model": "muse-glimmer:30b", "latency_ms": 4456, "ok": true, "fell_back_from": [], "error": null}
]
```

Both answers gave the same figure, £0.00 of net VAT for Oct–Dec 2026, because code computes the figure and checks it whichever model writes the words.

## Reproduce it

```bash
S=$(curl -s -X POST "https://api.accnomos.com/demo/session?kind=company" | python3 -c "import sys,json;print(json.load(sys.stdin)['session'])")
curl -s -X POST https://api.accnomos.com/books/ask -H "X-Demo-Session: $S" -H "X-AI-Route: local_only" \
  -H "Content-Type: application/json" -d '{"question":"How much VAT do I owe this quarter?"}'
curl -s https://api.accnomos.com/ai/calls
```

The tests are in `services/runtime/tests/test_ai_route.py`. They cover:
- the order for each route;
- local first moving to the Meta API on an unclear reply or an outage;
- local only never reaching the Meta API;
- voice input switching off under local only.
