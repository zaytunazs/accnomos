# Numbers audit: every measured figure in the judged docs against its source (28 Oct 2026)

Files checked: `README.md`, `docs/HONESTY.md`, `docs/META_MODELS.md`, `docs/ARCHITECTURE.md`, `docs/DEMO.md`, `docs/submission/*.md`.
"Fixed" means the doc quoted an older or wrong figure and now quotes the source (or labels the older run). Reports and summaries were not edited.
Python test counts were checked with `pytest --collect-only` on this checkout; the web e2e (208) and Flutter (248) counts are the owner's gate figures and were not re-run here.

## Extraction evals (27 Oct, 200 gold documents, repairs + re-read + Verifier on)

| Number | Where | Source | Matches |
|---|---|---|---|
| Spark Open clean: 91 % all fields, 98/98/99 net/VAT/gross, side 100, status 94, 12.9 s | `docs/submission/META_MODELS.md` table; README row 51; JUDGING; HONESTY | `evals/runs/spark_open_200/summary.json` | yes |
| Spark Open messy: 93 %, 99/99/100, 100, 97, 13.1 s | same | `evals/runs/spark_open_messy_200/summary.json` | yes |
| Glimmer clean: 85 %, 98/98/100, 100, 88, 17.7 s | same | `evals/runs/glimmer_200_v2/summary.json` | yes |
| Glimmer messy: 80 %, 97/97/99, 100, 83, 24.1 s | same | `evals/runs/glimmer_messy_200_v2/summary.json` | yes |
| Verifier caught / missed / false alarms: 1/3/8, 0/3/3, 3/2/18, 5/2/26 (sums 1+0, 6, 11; 3+5, 4, 44) | submission META_MODELS; README row 51; HONESTY | `verification.doc_outcomes` in the four summaries | yes |
| Status without the Verifier 98 % in all four | submission META_MODELS; HONESTY | "98% without the verifier" in each run's `report.md` | yes |
| Latency "mean 22 s, max 40 s over 200 documents" | submission META_MODELS (Latency bullet) | v2 summaries: 17.7 / 24.1 s mean, 41.7 / 111.3 s max; 22.16 / 39.81 s belongs to the earlier run | fixed |
| Glimmer "mean 22 s per document" | JUDGING | as above | fixed |
| Glimmer 22 s mean, 37 s max | `docs/META_MODELS.md` | 37.21 s is the 60-document run; current values above | fixed |
| 18-24 s per document | submission META_MODELS | v2 means 17.7 and 24.1 | yes |
| Spark Open "about 13 s per document" | README, HONESTY, submission | 12.9 / 13.1 s | yes |
| 88 % all fields, side 100, status 93 (Glimmer messy, earlier run) | README rows 44 and 92, HONESTY, `docs/META_MODELS.md`, DESCRIPTION | `evals/REPORT_glimmer_messy_200_2026-10-27.md` (88 / 100 / 93) | fixed: labelled "earlier run, without repairs, re-read or Verifier" and the current figures added next to it |
| 88 % quoted as the figure to use for the 200-document run | DESCRIPTION (editing rules and 400-word text) | v2 runs | fixed: 400-word text now 85/80 and 91/93 (398 words) |
| 73 % all fields on 60 documents, supplier/VAT/gross 100, date 98, net 97, status 80, VAT number 95 | README row 43, HONESTY, `docs/META_MODELS.md` | `evals/REPORT_glimmer_messy_60_2026-10-27.md` | yes |
| Replay of stored readings: 88 -> 91 %, net 93 -> 97 %, status 95 %, false passes 9 -> 11 | README row 92, HONESTY | `evals/harness/replay.py` output, quoted in `docs/reviews/extraction-quality-2` | not re-run here (a replay of the earlier run, now labelled as before the live run) |
| Supplier-VAT replay: false passes 6 -> 2, 193 -> 197 status matches | README row 92, HONESTY | `evals/runs/supplier_vat_replay/report.md` | yes |
| Claude judge agrees on 79/200 (167/200 with minor) | HONESTY, `docs/META_MODELS.md` | `evals/JUDGE_glimmer_messy_200_2026-10-27.json` | not re-derived (JSON not recounted) |
| Judge on 60: none 18, minor 15, major 22, unparsed 4 | `docs/META_MODELS.md` | `evals/JUDGE_glimmer_messy_60_2026-10-27.json` | not re-derived |
| "evals/runs/spark_open_200 once it lands" / "eval pending" / "0 extra catches" as the whole verifier story | HONESTY, ARCHITECTURE, `docs/META_MODELS.md`, DESCRIPTION, VIDEO_SCRIPT | the four summaries | fixed: results quoted, 20-document run kept and labelled |

## Verifier, Ask, intake, bank, Autopilot, crop

| Number | Where | Source | Matches |
|---|---|---|---|
| Verifier 20 docs: 17/18 agreed, 94 %, 0 extra catches, 1 false alarm, 7.6 s | README, HONESTY, ARCHITECTURE, META_MODELS (both) | `evals/REPORT_verifier_glimmer_messy_20_2026-10-27.md` (94 %, 7.57 s) | yes |
| Ask numbers exact 28/32 Glimmer, 31/32 Qwen; 4/5 action cards each; 4/35 timeouts quoted as current | README row 45, HONESTY, `docs/META_MODELS.md` | `evals/runs/ask_40/report.md`: 32/32 both; cards 3/5 and 4/5; 0 timeouts (28/32, 31/32 and 4 are the "before" column) | fixed |
| Ask 32/32, 29/32 own words, citations 32/32, median 16 s (54 s before), Qwen 14 s, slowest 50 s | README row 96, HONESTY, submission, JUDGING | `ask_40/report.md` (16.4 / 49.8 s; Qwen 13.9) | yes |
| Mail intake 12/17 kept, 11/11 decoys, triage filter 13/13, category 5/5, 5 of 17 missed | README, HONESTY, META_MODELS (both), JUDGING | `evals/runs/mail_intake/report.md` | yes |
| Bank matching 83/83, 83/106 (78 %), was 48 %, part 20 of 106 | README, HONESTY, META_MODELS, JUDGING | `evals/runs/bank_matching/report.md` | yes |
| Autopilot L2: 467 documents, 154 clean 0 (verifier on) / 1 (off), 139 messy 0, 42 re-photographed 0, 17 in 467 = 3.6 %, 0 in 407, 75 of 200 missed, 132 vs 148 correct posts, 21 of 32 before the rule | README, submission META_MODELS, DESCRIPTION, VIDEO_SCRIPT, JUDGING | `evals/runs/autopilot_l2/report.md`, `docs/reviews/autopilot-eval/REVIEW.md` | yes |
| Autopilot "times" | submission META_MODELS | report: mean 44.1 s on / 40.8 s off, other jobs shared the GPU | not quoted as a figure |
| Code crop mean IoU 0.88 vs 0.48 (0.882 / 0.475), 19 of 20 at 0.8+ | HONESTY, META_MODELS (both) | `evals/REPORT_crop_code_20_2026-10-27.md` | yes |
| Gold ledger2: 92 + 90 tests | JUDGING | `pytest --collect-only`: 182 together | yes |

## Test and build counts

| Number | Where | Source | Matches |
|---|---|---|---|
| Runtime 1,176 / 642 / 675 passed; ledger 33; connectors 34/37 | README, HONESTY, CHECKLIST, JUDGING | gate: runtime 1260 (collect: runtime 1181 + ledger 36 + connectors 47 = 1264, less skips) | fixed (1260, "all Python under check.sh") |
| Evals 153 / 258 | README (153), others (258) | `cd evals && pytest -q tests`: 258 passed | fixed (README 153 -> 258) |
| Relay 102 | README, HONESTY, DEMO (x2), CHECKLIST, JUDGING | `services/hmrc-relay`: 119 collected | fixed |
| Web e2e 44 / 56 / 107 / 170 / 191 / 195 | README (4 places), HONESTY, CHECKLIST, JUDGING | gate: 208 | fixed (history rows say "when written") |
| Per-project split 88 desktop + 80 phone + demo | README e2e row | not re-countable here | removed |
| Flutter 148 / 158 | HONESTY, CHECKLIST, JUDGING, VIDEO_SCRIPT | gate: 248 | fixed |
| "Flutter never analysed or tested" | README, DEMO | contradicts the 248-test gate | fixed |
| 29 e2e spec files | JUDGING | `ls apps/web/e2e/*.spec.ts`: 35 | fixed |
| 50 reviewed branches (was 46) | JUDGING | 50 `docs/reviews/*/REVIEW.md` | fixed |
| Books.xlsx 13 sheets | README | `SHEETS` in `projection.py`: 13 | yes |
| Word counts 150-word text 149; 400-word text 399 -> 398 | DESCRIPTION | awk count between the rules | fixed |

## Hand runs and other figures (no committed log)

| Number | Where | Source | Matches |
|---|---|---|---|
| "40 s, 9/9 code checks" first live read | README row 42 | maintainers' hand run, no log (stated in the README) | not verifiable |
| "7 s" Spark Open real call | README, HONESTY, DESCRIPTION, JUDGING, CHECKLIST, VIDEO_SCRIPT | one call, no log (stated) | not verifiable |
| "20-40 s on local Glimmer" for one sample receipt | DEMO, VIDEO_SCRIPT | v2 means 17.7-24.1 s, max 41.7 / 111.3 s | consistent, not a measured range |
| Muse Image 12 images, USD 0.12 | META_MODELS (both) | commit `f39cb2d` message | not re-checked |
| Seed: 40 entries, 36 gold docs, 25 unread; extended 59 events; GBP 17,949.78 owed | README row 72, DEMO | `tools/seed_demo.md`, `docs/reviews/seed-demo-2/REVIEW.md` | yes (checked against both) |

Note on `evals/runs/glimmer_messy_200/summary.json`: it reads 86 % all fields, side 98 %, status 93 %, net 93 %, while that folder's `report.md` and `evals/REPORT_glimmer_messy_200_2026-10-27.md` say 88 % and side 100 %. The docs cite the report (88 %) and now label it as the earlier run. The mismatch is inside the evals folder and was not edited.
