# Honesty: what is real, sandbox, demo, or not yet

Checked on `claude/judges-docs`: `pytest` passes in `packages/ledger` (30), `packages/connectors` (19), `services/hmrc-relay` (39) and
`services/runtime` (269); `pnpm run build` in `apps/web` passes (all 19 static pages). `evals` has no tests. The Flutter app was **not** built or tested here.
Most live-run notes come from the README and the review files, not from this check. We could not reach accnomos.com from this session, so the live site is unchecked.

## Sandbox, demo or synthetic

| Item | Truth |
|---|---|
| HMRC | **Sandbox only.** The relay defaults to `test-api.service.hmrc.gov.uk`. No production credentials, no real filing. Relay tests mock HMRC. The web submit flow is built and type-checked; the end-to-end browser run against the sandbox is **still pending** |
| Demo data | The company (Bramblewood Joinery Ltd), receipts, bank CSVs and the eval gold set are fictional and generated (Qwen as a test-data generator, not in the product). The grey "SAMPLE — FICTIONAL COMPANY" banner appears on every app page except `/privacy`, **including when signed in** |
| Signed-out web pages | Home tiles, Review cards, the voice-note card, Ask thread and the lower half of the **VAT return** page (a table, a "Reviewer's note (Muse Spark)" and a "Submit to HMRC (sandbox)" button that only prints "Sandbox submission would happen here") are **static mock-ups**. The live nine boxes and the working *Connect to HMRC (sandbox)* card sit above them |
| Evals | Synthetic renderings, so real phone photos will score lower. The Meta-API paths (Muse Spark extraction, Muse Voice, SAM 3.1, Spark Open on Baseten) are unit-tested against stubs only |

## Verified live vs not

| Verified by a real run | Written and tested against fakes, **not yet run for real** |
|---|---|
| Microsoft sign-in on the web (personal account); folder creation; upload → scan → Glimmer on our Spark → approve → ledger event → VAT boxes (26–27 Oct) | HMRC connect and submit in a browser; Outlook intake; Files page against a real OneDrive; Books.xlsx opened in Excel; deadlines; VAT period picker and date-in-period warning; contacts; jobs; bank; vehicles and mileage; Autopilot end to end |

## Not built, or not as the marketing might read

- **No separate LLM Reviewer.** The card's "why" line is composed by code ("Checker, code"). Muse Spark writes answers only in *Ask* (key mode).
- **`muse-wonder-1.0` is not called.** The README used to say it plans commands; that code is on the unmerged `claude/chat-actions` branch.
- **SAM 3.1 crop is off by default** (`SAM_CROP=1`); its request shape is unverified. The default crop is plain code.
- **Verifier numbers are small:** 20 documents, Glimmer checking Glimmer, 0 extra errors caught, 1 false alarm. Baseten's Spark Open slug is unconfirmed, and the demo deployment sets no Baseten key.
- **Muse Voice Transcribe:** wire format from research notes, not checked against dev.meta.ai; no live mic run; key mode only. Meta has no text-to-speech model.
- **"On my own machine" means "the machine running the runtime".** Our demo runtime and Ollama are on our DGX Spark. A user's laptop is not reachable from `api.accnomos.com`.
- **Ledger files are not tamper-evident** (no signatures or hash chain). Undo of an approval is a reversing event; if the VAT period was already submitted, the correction belongs in the current period.
- **OneDrive only.** Google Drive is planned. HEIC photos are copied but not read yet. No flat-rate scheme, no annual accounting scheme in deadlines, no fuel scale-charge calculation, no sales-invoice creation (jobs only record an invoice number).
- **VAT periods:** the web `/vat` picker and the Android VAT tab list the current period and the 8 before it; the date-in-period warning now fires on scans (a warning only). Limits: "submitted" means *a receipt saved in `05 VAT returns/` by our relay submission*. The runtime has no HMRC token, so a return filed elsewhere (or a deleted receipt) shows as open; HMRC's own obligations are in *Connect to HMRC*. Android sends no stagger (the phone has no such setting yet), so it always shows calendar quarters. The runtime's own period key (`26A4` style, saved as `calculated_for` with a receipt) is a placeholder for calendar quarters; submission uses the key from HMRC's obligations. Tested against fakes only.
- **Unmerged work is not claimed:** `claude/invoicing` and `claude/chat-actions` exist as branches but are not in this one.

## Sign-in build state

- **Web:** MSAL v5, redirect URIs registered for `http://localhost:3000/auth/callback.html` and `https://accnomos.com/auth/callback.html` only.
- **Android (0.2.0+2):** MSAL with PKCE. The redirect URI contains the APK signing hash; the app defaults to the **debug** key's hash, and release builds need their own hash registered with Microsoft (`assets/msal_config.json` has `broker_redirect_uri_registered: false`). If it is not, the app says so in plain words and stays on sample data. Whether a release build signs in has not been confirmed here.
- **Android gaps:** *Files* tab is a placeholder; Ask voice says "arrives in the next update"; Home tiles are static; no HMRC filing (the Home copy mentions it; the VAT tab only shows the boxes).

## TODOs flagged in the code

- `apps/mobile/lib/services/settings.dart`: move the Meta API key to `flutter_secure_storage` before any real user data (it is not stored securely today).
- `services/runtime/app/routes_jobs.py`: sales invoicing is not on `main`; invoice-sent is a manual step.
- `services/runtime/app/ai/verify.py`: Baseten model slug not confirmed.
- `docs/DEV.md`: SAM request/response fixture must be replaced with a captured real response before turning it on.

## Provenance

All product code was written during the build period; coding assistants (Claude, Muse Code, a local Qwen) helped write it, and every merge was reviewed (`docs/reviews/`). The DGX Spark and Ollama setup predates the event and is infrastructure.
