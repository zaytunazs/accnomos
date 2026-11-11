# Devpost submission texts (PayPal AI Hackathon)

Paste field by field. Deadline: **Thursday 12 Nov 2026, 20:00 London time**. Placeholders in `<<…>>` are filled on
Devpost only, never in this repo. Every claim here is one `docs/HONESTY.md` allows; the judges' evidence page is
[`JUDGES.md`](JUDGES.md).

---

## Project name

Accnomos

## Tagline (≤ 200 characters)

AI bookkeeping and VAT for UK small businesses: PayPal invoices, payments, fees, payouts and disputes land in books you own, and the owner approves every posting.

(162 characters.)

## Video

`<<YOUTUBE URL (public)>>`

## Inspiration

UK small businesses get paid through PayPal and pay suppliers through it too, but the money arrives in their books by
hand: someone downloads a report, works out which invoice each payment belongs to, splits off PayPal's fee, and hopes
the VAT is right. Making Tax Digital means the VAT return has to come from digital records, so those hand-made entries
end up in a tax filing. We wanted the PayPal side of a small business to keep its own books, without taking the owner's
data into our database and without letting an AI post anything on its own.

## What it does

Accnomos keeps a UK small business's books in its own OneDrive or Google Drive and files VAT to HMRC; PayPal is where
it gets paid and pays its bills.

- **Get paid.** Every invoice can carry a PayPal pay link: Accnomos creates a real PayPal invoice with the same lines,
  VAT and business details, puts the link on the PDF and in the email, and can send PayPal's own reminder.
- **Sync PayPal.** Reads the PayPal account's transactions and proposes each one: gross, PayPal fee and net, matched to
  the invoice it pays. A sale with no invoice waits until the owner chooses its VAT. Nothing posts until the owner
  approves.
- **Ask about PayPal.** "What did PayPal cost me this quarter?" and "How much is in PayPal?" are answered with a
  figure worked out by code from the PayPal entries in the books, and explained in plain English.
- **Tie-out.** PayPal's own balance (with the time PayPal last refreshed it) against the PayPal account in the books,
  with the difference explained: waiting for approval, never posted (withdrawals, refunds, the opening balance), or
  unexplained.
- **Pay bills.** On a supplier bill's due date, Accnomos offers to pay it with a PayPal Payout to the supplier's saved
  PayPal email. The owner approves; the payment posts only when PayPal reports SUCCESS (about 30 seconds in the
  sandbox). A retry can never pay twice.
- **Disputes.** When a customer opens a PayPal dispute, Accnomos builds an evidence pack from the books (the invoice,
  the payment, the dates), checks every figure and date in the draft by code, and sends it only after the owner reads
  and approves it.
- **VAT.** Approved PayPal sales are ordinary entries in the ledger, so they are in the VAT return Accnomos works out
  and files to HMRC (HMRC's sandbox in the demo).

The rule throughout: **the AI proposes, code calculates in pence, the owner approves.**

## How we built it

- **Web app:** Next.js and TypeScript (`apps/web`), the PayPal screens on Invoices (Sync PayPal, tie-out, disputes)
  and Purchases (Pay bills with PayPal). **Android app:** Flutter (`apps/mobile`), the same runtime API (it has no
  PayPal screens yet: the PayPal features are on the web).
- **Runtime:** a stateless FastAPI service (`services/runtime`). It holds no customer database: each request carries
  the user's own drive token, and the books are files in the user's OneDrive or Google Drive, with an append-only
  ledger and a VAT engine that works in integer pence.
- **PayPal APIs used** (`services/runtime/app/payment_providers.py`):
  - **Invoicing v2:** create, send, remind and cancel invoices; read an invoice back to find its payment.
  - **Transaction Search** (`GET /v1/reporting/transactions`, 31-day windows): the source for Sync PayPal.
  - **Balances** (`GET /v1/reporting/balances`): PayPal's own balance and its refresh time for the tie-out.
  - **Payouts v1:** one payout per bill, with a `sender_batch_id` derived from the bill, the amount and the attempt, so
    a retry after a lost answer returns the original batch instead of paying again; a bill posts only on SUCCESS.
  - **Disputes v1:** list and read disputes, provide evidence (notes plus a PDF from the books), send a message, accept
    a claim.
  - **Two modes:** *partner* mode (each business connects its own PayPal account through partner onboarding and
    `PayPal-Auth-Assertion`; written to PayPal's documentation, waiting for partner approval) and *direct* mode (the
    server's own sandbox REST app, used by the demo; it refuses live credentials).
- **AI at run time:** a hosted AI model drafts proposals (coding a PayPal purchase to an account, wording a dispute
  response, explaining a figure), with Anthropic as the backup provider; an open-weights model can run on our own
  server or in local mode instead. Code works out every amount and checks every figure a model writes into a dispute
  response, and every posting is a proposal card the owner approves.
- **Tests:** pytest against PayPal fakes written from PayPal's published schemas (`services/runtime/app/online_fakes.py`)
  and a mock transport; Playwright end-to-end tests for payment links; a smoke script that runs the same code against
  the real PayPal sandbox (`tools/payments_sandbox_smoke.py`).

## Challenges we ran into

- **PayPal's reporting delay.** Transaction Search can list a payment up to three hours after it happens, so a sync
  straight after a payment can show nothing. We show the balance's refresh time on screen and explain the gap in the
  tie-out instead of hiding it.
- **No future-dated payouts.** PayPal Payouts send at once, so "pay on the due date" means Accnomos pays the next time
  it is open on or after that date (writing to the books needs the owner's sign-in, so there is no overnight job).
- **The real sandbox disagreed with the docs.** Invoice create answered with only a `self` link, so the invoice id is
  read from it; the duplicate-payout refusal links the original batch inside `details[].link`. Both are fixed and
  noted. A payout to a registered sandbox account then went from PENDING to SUCCESS in about 30 seconds.
- **Fees and VAT.** PayPal's fee is VAT-exempt and comes out of the gross, so each payment becomes three figures and a
  clearing account (1240 PayPal clearing) that the bank payout later clears, so money is never counted twice.

## Accomplishments that we're proud of

- The whole loop runs on one set of books the owner owns: invoice, PayPal payment, fee, tie-out, supplier payout,
  dispute evidence, VAT return.
- Nothing reaches the ledger without the owner's approval, and an AI never does the arithmetic.
- A retried payout cannot pay a supplier twice, and a changed supplier payment detail on a bill is flagged, never
  copied into the payee list.
- An honest record of what has met PayPal's real sandbox and what has only met fakes (`docs/HONESTY.md`).

## What we learned

- Reporting APIs and payment APIs run on different clocks; reconciliation has to show "as of" times, not pretend to be
  live.
- Idempotency keys have to be derived from the business event (bill, amount, attempt), not generated per request, or a
  retry is a second payment.
- Writing fakes from the published schemas first, then running against the sandbox, found the two places where the
  sandbox's answers differ from the documentation.

## What's next

- PayPal partner approval, so each business connects its own PayPal account (partner mode is written and tested
  against fakes).
- Run the remaining calls against the sandbox: Invoicing remind, itemised invoices, Disputes and the capture read for
  the fee.
- PayPal webhooks, so payments are proposed without opening the app.
- PayPal screens in the Android app.

## Built with

`python` · `fastapi` · `pydantic` · `httpx` · `typescript` · `next.js` · `react` · `tailwindcss` · `flutter` · `dart` ·
`paypal` · `paypal-invoicing-api` · `paypal-transaction-search-api` · `paypal-payouts-api` · `paypal-disputes-api` ·
`microsoft-graph` · `onedrive` · `google-drive` · `hmrc-mtd-vat-api` · `pytest` · `playwright` · `docker` · `nginx` ·
`anthropic`

## AI tools used to build it

- **Coding assistant:** Anthropic's AI coding assistant wrote most of the code under the owner's direction; the owner
  set the requirements, reviewed the work and made every product and compliance decision. Commits it helped with carry
  a `Co-Authored-By` line in `git log`.
- **AI inside the product (run time):** a hosted AI model, with Anthropic as the backup provider, or an open-weights
  model on our own server or in local mode; speech-to-text for spoken questions; an image model that crops receipt
  photos. In the PayPal features the AI codes PayPal purchases to accounts and drafts dispute responses; code works out
  every amount and VAT figure, and the owner approves every posting.
- **PayPal is central:** every feature in this entry is a PayPal API call or its result in the books.

## Testing instructions for judges

**Web (recommended):** open `https://accnomos.com` and press **Try the demo**: no sign-in, your own copy of a fictional
company's books (guide at `https://accnomos.com/judges`).

1. **Invoices:** the **PayPal** panel: press **Sync PayPal**. In the demo, with no PayPal connected, this reads a fixed
   sample history, labelled "Sample PayPal history for this demo" (it is not PayPal data). Each card shows gross,
   PayPal fee and net, the invoice it pays, the entry approving would post, and **Approve** / **Reject**.
2. **Ask:** after approving a PayPal card, ask *What did PayPal cost me this quarter?* or *How much is in PayPal?*: the
   figure is worked out by code from the PayPal entries in the books (not a live PayPal call; the tie-out on Invoices
   is the screen that reads PayPal's own balance when PayPal is connected).
3. **Invoices › PayPal disputes:** one SAMPLE dispute built by code. **Build evidence** → read the preview → **Send to
   PayPal (demo)** records it as sent; nothing goes to PayPal.
4. **To use PayPal's real sandbox in the demo:** Settings › Online payments → **Connect PayPal (test mode)**. Then on
   Invoices, **Add payment link** on an unpaid invoice → PayPal → **Make payment link**, open the link and pay as a
   sandbox buyer: `<<SANDBOX BUYER LOGIN>>` / `<<SANDBOX BUYER PASSWORD>>`. Note: every demo visitor's links pay into
   the same Accnomos sandbox business account, and PayPal's Transaction Search can take up to 3 hours to list a payment,
   so **Sync PayPal** may show it only later; the invoice's own payment is also looked for each time you open Invoices
   and shown under **Paid online: waiting for your approval**.
5. **Purchases › Pay bills with PayPal** (after step 4): save a supplier's PayPal email (a sandbox account:
   `<<SANDBOX PAYEE EMAIL>>`); a bill due today shows under **Due today** → **Approve payment** → **Pay £…** sends a
   sandbox payout.
6. **VAT** (`/vat`): the nine boxes from the ledger; filing goes to HMRC's sandbox with a test user HMRC makes for the
   demo.

**Android:** install the newest `android-*` APK from `https://github.com/zaytunazs/accnomos/releases` and press **Try
the company demo**. The PayPal screens are on the web; the app shares the same books and runtime.

**Code and evidence:** `https://github.com/zaytunazs/accnomos`; what each PayPal feature is verified against (real
sandbox or fakes) is in `docs/submission/paypal/JUDGES.md` and `docs/HONESTY.md`.

## Significant updates during the submission period

The repository's first commit is **26 Oct 2026** (22:29 UTC), inside the submission period (1 Oct – 12 Nov 2026);
nothing in it existed before that. Accnomos was first built for another online hackathon (26 Oct – 4 Nov 2026): the
ledger, the VAT engine, the web and Android apps, and on **28 Oct 2026** the first payment links (PayPal invoices on
Accnomos invoices, PayPal receipts through a clearing account, payouts matched to the bank). For this hackathon, on
**11 Nov 2026** (and the final changes up to the 12 Nov deadline), we made PayPal the centre of the product: direct
mode and the first runs against PayPal's real sandbox (Invoicing, Transaction Search, Balances, Payouts), **Sync
PayPal**, PayPal questions in Ask, the **tie-out** against PayPal's balance, the owner's VAT choice on unmatched sales, **bill pay by PayPal
Payouts** with idempotent batch ids, **PayPal disputes** with evidence from the books, itemised PayPal invoices with the
business's details, and PayPal as the default way to get paid. Dates are in `git log`.
