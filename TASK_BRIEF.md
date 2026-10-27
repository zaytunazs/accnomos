# Task: Intake formats — multi-page PDFs, HEIC/HEIF photos, scanned PDFs, email bodies as receipts; same checks, same cards

Accnomos monorepo (public; UK English; no secrets). Read first `services/runtime/app/{pipeline.py,inbox.py,intake.py,crop.py}`,
`app/ai/extract.py` (what the model is sent: PNG/JPEG bytes?), `packages/connectors` (Outlook intake attachment filter: which content
types are kept), `deploy/Dockerfile.runtime` (system packages available: is `libheif`/`poppler` there?), `evals/gold/mail/*`, `docs/INBOX.md`.

## Deliverables
1. **PDF**: a PDF with text is read page by page; the first page's text plus a render of the first page go to the model; a
   multi-page invoice is one document (not one per page); a PDF with several receipts (a scanner batch) is split only when the
   user asks (not in scope — document it). Rendering with what is in the image already (`pdf2image`/`pypdfium2` — check what
   installs cleanly; add to pyproject and the Dockerfile; `uv lock`).
2. **HEIC/HEIF** (iPhone photos): converted to JPEG on arrival (`pillow-heif` if it installs; otherwise reject with a clear message
   that says "export as JPEG"); EXIF orientation respected for every image.
3. **Email body receipts** (Uber, Amazon, SaaS invoices with no attachment): the Outlook intake keeps a message whose body looks like a
   receipt (code heuristic: a currency amount and the words total/VAT/invoice/receipt) and saves it as `<subject>.eml.txt` in
   `00 Inbox`; the pipeline reads text documents through the same extractor prompt (text instead of image). Tests with the gold mail
   fixtures.
4. Size and safety: 25 MB cap, image bombs refused (pixel count), PDFs limited to 20 pages; every new path covered by `test_security*`.
5. README intake row, `docs/INBOX.md`, HONESTY line for what is unverified (real HEIC from a phone).
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
