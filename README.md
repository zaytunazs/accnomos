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

## What works today (verified live, updated as we go)

| Date | Verified |
|---|---|
| 26 Oct | Microsoft sign-in (MSAL v5 + redirect bridge) on a personal account; `Apps/Accnomos` tree + README created in the user's OneDrive |
| 27 Oct | Upload → `00 Inbox` → scan → **Muse Glimmer 30B on our DGX Spark** reads the receipt (40 s, 9/9 code checks) → proposal in `_System/proposals` → **Approve** → immutable ledger event in `_System/Ledger/events` → **VAT 9 boxes computed by code** from those events (`/books/vat`) |
| 27 Oct | Eval on 60 synthetic messy receipts (Glimmer, local): supplier 100%, VAT total 100%, gross 100%, date 98%, net 97%; proposed/needs-a-look decision 88% — `evals/REPORT_glimmer_messy_60_2026-10-27.md` |
| 27 Oct | HMRC relay: OAuth, fraud-prevention headers v3.3, VAT MTD endpoints — unit-tested against mocks; sandbox call pending credentials |
| 27 Oct | **HMRC (sandbox) in the web app:** on `/vat`, under the live 9-box return, *Connect to HMRC (sandbox)* (OAuth with PKCE through the relay, tokens only in the tab's `sessionStorage`) → open obligations → confirm the boxes and tick the legal declaration → submit → receipt saved to `05 VAT returns/<periodKey>/` in your OneDrive. Built and type-checked; end-to-end browser run pending. See `docs/HMRC.md` |
| 27 Oct | **Outlook intake (F10):** Settings → *Outlook intake* asks for `Mail.Read` only when switched on → *Check my inbox now* (`POST /mail/scan`) copies likely receipts/invoices from the last 14 days into `00 Inbox`, deduplicated, with a log in `_System/Intake/`. Web build passes; runtime tests written against fake mailbox/storage; live mailbox run pending |

## Outlook intake

Turn it on in Settings and Accnomos asks Microsoft for one extra permission, `Mail.Read` (read-only). *Check my inbox
now* looks at emails with attachments from the last 14 days and, with plain code (no AI), keeps PDF/JPEG/PNG/HEIC files
between 10 KB and 15 MB that look like receipts or invoices (sender outside your own domain; words such as receipt,
invoice, bill, order, payment, VAT or remittance in the subject or file name). **Read:** message date, sender, subject
and those attachments. **Written, all in your own folder:** the file as `00 Inbox/<date>_<sender-domain>_<name>`,
`_System/Intake/seen.json` (so nothing is copied twice) and `_System/Intake/log/<yyyy-mm>.jsonl`. **Never:** sending,
moving, flagging, marking as read or deleting mail, reading message bodies, or keeping anything on our server. The
last check time is kept only in this browser. HEIC photos are copied but wait in `00 Inbox` until the reader supports them.

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
