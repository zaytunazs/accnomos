# Review: `claude/intake-formats`

Second-agent review of the intake-formats task (`TASK_BRIEF.md`): multi-page and scanned PDFs, HEIC/HEIF photos,
receipts written in an email body, size and safety limits, docs.

## What was checked

- `pytest -q` in `services/runtime` (896 passed, 1 skipped: the live-Graph seed test), `packages/connectors` (46),
  `packages/ledger` (35), `services/hmrc-relay` (102). `apps/web`: `pnpm run build` passes.
- The branch arrived with `pypdfium2` and `pillow-heif` **not installed** in the test environment, so the five tests
  that use the real libraries were skipped and the PDF/HEIC paths had only run against stand-ins. They were installed
  (`pypdfium2` 5.14.0, `pillow-heif` 1.8.1) and every test now runs.
- Read the whole diff: `app/formats.py`, `pipeline.py`, `inbox.py`, `intake.py`, `routes_extract.py`, `ai/extract.py`,
  `ai/verify.py`, the Graph connector, the web copy, the docs. Product rules: nothing is stored server-side (email
  bodies go to the user's own `00 Inbox`); the model only reads, code checks and files; document and email text is
  sent between markers as data; gold mail fixtures B01–B06 are fictional (`.example` domains, `AAMk-sample-*` ids).

## What was fixed

| Commit | Fix |
|---|---|
| `dd68bae` | `uv.lock` had not been regenerated for `pypdfium2` and `pillow-heif`; now locked. |
| `31565ff` | **PDFium crash under concurrency.** `prepare()` runs in worker threads (`asyncio.to_thread`) and PDFium is not thread-safe; two PDFs at once crashed the process (reproduced: the new test segfaults without the fix). PDF reading now holds a module lock. |
| `31565ff` | **Any `.txt` in `00 Inbox` was sent to the model** and turned into a card. The existing test's `notes.txt` had been renamed to `notes.docx` to get around this; restored. Only `.eml.txt` (an email body saved by intake) is now a text document. |
| `31565ff` | Missing tests: concurrent PDF reads never overlap in PDFium; HEIC with EXIF orientation 6 is turned upright once (not twice); a real 2-page PDF through `POST /extract` (page 1 text + render sent, page 2 not, `.pdf` filename, `SOURCE` note, digest of the PDF); a `notes.txt` is left alone. |
| `e592cdd` | Docs: HONESTY/README no longer say the libraries are untested and unlocked; INBOX.md says other `.txt` files are ignored and PDFs are read one at a time. |

## What remains

- No real HEIC from a phone and no real supplier PDF has been read; the tests make their own files (`pillow-heif`, `fpdf2`).
- The Docker image (`deploy/Dockerfile.runtime`) was not built here; its `import pypdfium2, pillow_heif` check is untested.
- Graph: `list_without_attachments` (`receivedDateTime ge … and hasAttachments eq false` with `$orderby receivedDateTime desc`) and `message_text` (`Prefer: outlook.body-content-type="text"`) have never been called against a real mailbox; Graph may reject or slow that filter/orderby combination.
- The body-receipt heuristic is tested on six fictional emails only, not on real Uber/Amazon/SaaS mail.
- A multi-page PDF is read from page 1 only; a scanner batch is not split (documented, out of scope).
- If extraction fails after the Inbox scan has swapped a HEIC for its JPEG, the JPEG stays in `00 Inbox` and the HEIC is in `_System/Originals`; the next scan retries the JPEG (no data lost, but untested).
- The PDF lock serialises PDF reading per process; a burst of large PDFs on one worker will queue. Not measured.
- `ruff`/type checks were not run.

## How to verify by hand

Install the runtime with its new dependencies (`uv sync` or `pip install -e services/runtime`), start it, and in the
web app upload: a multi-page supplier PDF (the card should say "PDF, N pages: page 1 read" and the total should match
page 1), a scanned PDF with no text layer ("no text layer (a scan), read from the image"), and a HEIC photo taken on an
iPhone in portrait (it should be filed as an upright `.jpg`, with the HEIC in `_System/Originals` when it came through
`00 Inbox`). Drop a `notes.txt` into `00 Inbox` and scan: it must stay there with no card. Then turn on Outlook intake
on a test mailbox that has an Uber or Amazon receipt with no attachment and a marketing email: *Check my inbox now*
should save only the receipt as `<date>_<sender>_<subject>.eml.txt`, and the next Inbox scan should give it a card
"Email text, read without an image".
