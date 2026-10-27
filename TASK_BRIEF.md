# Task: Submission pack for the Meta Global AI Developer Hackathon (Indie track) — drafts only, nothing published

Accnomos monorepo (public; UK English; no secrets; every claim must be true of main today — read `README.md` "What works today",
`docs/HONESTY.md`, `docs/ARCHITECTURE.md` (models table), `docs/DEMO.md`, `docs/reviews/*/REVIEW.md`). Deadline Wed 4 Nov 2026 21:00 ET.
The owner (Zohaib Sharif, Zaytuna Business Services Ltd, solo) submits; you draft into `docs/submission/`.

## Deliverables (all Markdown, dense, no marketing fluff, UK English)
1. `docs/submission/DESCRIPTION.md`: 150-word and 400-word versions of the project description; a one-line tagline; the problem
   (UK small businesses, MTD VAT, bookkeeping cost), the approach (AI proposes, user approves, code calculates; books in the user's
   OneDrive; no user database), what is built, what is honest about limits.
2. `docs/submission/META_MODELS.md`: every Meta model used and exactly where (Muse Glimmer 30B local via Ollama for reading
   receipts/Ask; Muse Spark 1.3 via the Meta Model API; Muse Voice Transcribe; Muse Image for the brand assets; SAM 3.1 crop;
   Spark Open on Baseten as the verifier) with file paths and which are verified vs modelled; token/cost notes if present in the repo.
3. `docs/submission/VIDEO_SCRIPT.md`: a 3-minute demo video script with timestamps, exact clicks (from `docs/DEMO.md`), on-screen
   captions, and a shot list (web at 1280 px, phone emulator at 390 px); plus a 30-second cut.
4. `docs/submission/JUDGING.md`: how the project maps to likely criteria (technical depth, use of Meta models, impact, completeness,
   honesty) with evidence links into the repo; a "how to run it in 10 minutes" section (test mode, no accounts needed) checked
   against `docs/DEV.md`.
5. `docs/submission/CHECKLIST.md`: everything the owner must do by hand before submitting (Play listing status, demo account,
   HMRC sandbox secrets, Entra hash, video upload, repo public check for secrets — list the grep commands), each with the file or
   console where it happens.
No code changes. Commit in small steps; do not push. Finish with `git log --oneline -8` and five claims you deliberately left out as unproven.
