# Review: `claude/invoicing`

Second-agent review of the sales invoicing task (`TASK_BRIEF.md`): create, PDF, send via Outlook, track payment,
Muse-drafted reminders.

## What was checked

- **Tests run** (all green after the fixes below):
  - `packages/connectors`: 21 passed
  - `packages/ledger`: 16 passed
  - `services/runtime`: 194 passed (191 before review + 3 added)
  - `services/hmrc-relay`: not touched by this branch, not run
- **Web build:** `apps/web && pnpm run build` passes (`/invoices` and `/invoices/new` prerender).
- **Environment note:** on this machine, `accnomos-connectors` and `accnomos-ledger` are installed editable from a
  *sibling* checkout (`repo-lane-f`), so a bare `pytest -q` imports the wrong code: `MailSender` is missing and one
  ledger VAT test fails. Run with this lane's sources first on the path:
  `pytest -q -o "pythonpath=<repo>/packages/connectors/src <repo>/packages/ledger/src"`. This is not a code bug.
- **Diff read as a reviewer:**
  - `invoicing.py`: per-line pence and VAT, half-up rounding, client totals ignored. Number allocation never reuses a
    number. Draft → sent → paid / void. The email goes before the status changes. The sale's event id comes from the
    invoice number, so a retry never posts twice. Voiding a sent invoice appends a reversal and is refused while a
    bank line is matched to it. Path traversal is blocked by `ID_RE`.
  - `routes_invoices.py`: `confirm` is a `StrictBool` on both send routes. 404/400/409 mapping. Logo uploads are
    limited by type and size.
  - `pdf.py`: Latin-1 fallback, and a bad logo does not stop the render.
  - `ai/remind.py`: code supplies the facts, then code checks the model's draft (no invented figures, no links, the
    invoice number must appear). Bank details never go to the model. Falls back to a draft written by code.
  - `vat.py` fix: an undone sale nets off Box 1 and Box 6.
  - `GraphMailSender`
  - Web client: integer pence, the same rounding as the runtime, `Mail.Send` asked for only on send, the
    confirmation tick, and the signed-out sample labelled "SAMPLE — FICTIONAL COMPANY".
- **Contacts:** `contacts.json` shape and path match the contacts brief (`_System/Contacts/contacts.json`, a list
  with `kind`/`email`/`address`/`vrn`). The file is read-only here.
- **No user data server-side:** everything is written through the user's storage provider; the runtime keeps no state.
- **README:** the "Sales invoices" row and the "Invoicing" section match the code: button labels exist, the
  limitations are stated, and it does not claim a real mailbox was used.

## What I fixed

- `a9f9cb0`: the reminder draft written by code started a sentence in lower case ("Hello,\n\na quick reminder…",
  "invoice INV-0001 … was due"). It now starts with a capital. Tests added for:
  - the fallback wording (not yet due / overdue / follow-up)
  - PDF rendering with non-Latin-1 text and a real, a corrupt and no logo
  - logo uploads over 1 MB refused (413) and not written

## What remains

- `GraphMailSender.MAX_INLINE` checks 3 MB of *raw* attachment bytes, but base64 inflates that by about a third,
  and Graph's 4 MB request cap applies to the encoded body. A 2.9 MB attachment would pass our check and be rejected
  by Graph with a GraphError rather than our friendly message. Invoice PDFs are tens of KB and logos are capped at
  1 MB, so this is low risk.
- If saving the copy to `03 Sales/invoices/sent/` fails after the email has gone, the invoice is saved as sent but
  the sale is not posted until the user retries ("Record it in the ledger now"). That retry path is built and
  tested. The sent copy would then be missing, and the preview re-renders from the invoice instead.
- In the web confirmation dialogs, the tick stays ticked if the user edits the To/Subject/Message after ticking.
- Not built (as the README says): credit notes, posting the receipt to 1200 Bank on *Mark paid*, voiding a paid
  invoice.
- Not verified against real services: sending from a real Outlook mailbox, the `Mail.Send` consent redirect,
  opening the PDF in a real viewer or printing it, and logo upload to a real OneDrive.
- Machine environment: the editable installs point at `repo-lane-f` (see above); reinstall from this checkout or use
  the `-o pythonpath` override.

## How to verify by hand

1. Start the runtime and the web app, sign in with a Microsoft account, and open *Settings* (or `/connect/business`).
2. Fill in the invoice profile (name, address, VRN such as `GB 123 4567 89`, sort code and account number) and upload
   a PNG logo. Check that `_System/Invoicing/profile.json` and `logo.png` appear in the OneDrive app folder.
3. Go to *Invoices* → *New invoice* and pick a customer (or type one, with your own email address). Add a line of
   7.5 hours at £45.00, standard rated. The live totals should show £337.50 net, £67.50 VAT, £405.00 total.
4. Tap *Save and preview*. Check the A4 PDF: supplier and customer blocks, number, dates, VAT summary, bank details,
   and "VAT reg no" in the footer.
5. Tick the confirmation and tap *Send via Outlook*. Microsoft should ask for `Mail.Send` once. Check:
   - the email arrives with the PDF attached and appears in your Sent Items
   - `03 Sales/invoices/sent/INV-0001.pdf` exists
   - the sale appears in the ledger and Books.xlsx, and on the VAT page (Box 1 +£67.50, Box 6 +£337.50)
6. Tap *Draft a reminder*. Nothing should be sent until you tick and confirm.
7. Tap *Mark paid*, or *Void* to see the reversal net the VAT back to zero.
