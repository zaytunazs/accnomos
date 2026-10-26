# Accnomos

**Accounting, intelligently done.** Your books stay in your own cloud. Meta AI does the work.

Bookkeeping and MTD VAT for UK small businesses, built for the Meta Global AI Developer Hackathon
(26 Oct – 4 Nov 2026, Indie track, problem statement "Build for Your World").

- **No user database.** Your books live in a folder you own (OneDrive first; Google Drive next).
  Disconnect the app and every file is still there, readable without us.
- **Meta AI on your terms.** Bring your own Meta Model API key, or run Muse Glimmer 30B on your own machine.
- **AI proposes, you approve, code calculates.** VAT boxes are computed by deterministic code from
  entries you approved; filing to HMRC needs an explicit tap.
- Multi-agent with verification: Intake → Extractor → Checker (code) → Reviewer → Verifier → Human → Poster → Filer.

## Layout

| Path | What |
|---|---|
| `apps/web` | Next.js PWA (Home · Review · Ask · Files) |
| `apps/mobile` | Flutter Android app, same runtime API |
| `services/runtime` | Stateless Agent Runtime (FastAPI): receives the user's cloud token + AI config per request, keeps nothing |
| `services/hmrc-relay` | Stateless HMRC relay: holds the HMRC client secret, adds fraud-prevention headers |
| `packages/ledger` | Append-only ledger events, projections, deterministic VAT 9-box engine, tests |
| `packages/connectors` | `StorageProvider` / `MailProvider` / `CalendarProvider` interfaces, Microsoft Graph implementations, fake provider + contract tests |
| `evals` | Synthetic gold set and the eval harness that grades Meta model outputs |
| `tools` | Owner-run scripts (keystore, dev helpers) |

## Meta models used (runtime path)

| Model | Role |
|---|---|
| Muse Glimmer 30B (open weights, Ollama, user's own hardware) | Receipt/invoice reading, categorising, tool calls |
| muse-spark-1.3 (Meta Model API, user's key) | Review, anomalies, explanations; cloud-mode extraction |
| sam-3.1 | Crop/split receipts in messy photos |
| muse-voice-transcribe-1.0 | Voice notes and voice questions |
| muse-wonder-1.0 | Plans multi-step commands |
| Muse Spark Open (Baseten) | Independent verifier (optional) |

## Honesty notes

- Everything in this repository was written during the hackathon building period. Pre-existing items: none in the code; the
  DGX Spark/Ollama host setup predates the event and is infrastructure, not product code.
- Demo data is synthetic and labelled "SAMPLE — FICTIONAL COMPANY". HMRC is sandbox only.
- Coding assistants (Claude, Muse Code, local Qwen) were used to write code; Meta models are the ones doing the work at runtime.
- Meta has no text-to-speech model; spoken answers use the device's own TTS.

## Running locally

See `docs/DEV.md` (written as the pieces land). Secrets go in `.env` (copy `.env.example`); never commit it.

## Licence

MIT — see `LICENSE`.
