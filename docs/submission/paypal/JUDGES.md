# Judges' guide: Accnomos and PayPal (one page)

Accnomos keeps a UK small business's books in its own OneDrive or Google Drive and files VAT to HMRC; PayPal is where
it gets paid and pays its bills. The AI proposes, code calculates in pence, the owner approves every posting.
**Try it:** `https://accnomos.com` → **Try the demo** (no sign-in). Click paths: [`DEVPOST.md`](DEVPOST.md#testing-instructions-for-judges).
**Everything is PayPal sandbox; nothing has run against live PayPal.** The full record is `docs/HONESTY.md`
(sections "Online payments (payment links)" and "Paying bills through PayPal (Payouts)"); the table below copies it.

## Feature → code → tests

Runtime paths are under `services/runtime/`; web paths under `apps/web/src/`.

| Feature | Where | Tests (all against fakes or a mock transport) |
|---|---|---|
| PayPal API client (all calls below) | `app/payment_providers.py` (`PayPalApi`); fakes from PayPal's published schemas in `app/online_fakes.py` | `tests/test_online_payments.py` (33), `tests/test_online_payments_direct.py` (10, direct mode request shapes) |
| Invoice with a PayPal pay link (Invoicing v2 create, send, read, remind, cancel; itemised lines with VAT as item tax) | `app/online_payments.py`; web `components/invoices/OnlinePayments.tsx`, `components/settings/OnlinePayments.tsx` | `tests/test_online_payments.py`, `tests/test_paypal_disputes.py` (itemised invoices: business details, part-paid as one line, fallback when PayPal totals differ); e2e `apps/web/e2e/online-payments.spec.ts`, `apps/web/e2e/invoice-payments.spec.ts` |
| Sync PayPal (Transaction Search → gross / fee / net proposals matched to invoices; owner approves or rejects) | `app/paypal_sync.py`, `app/routes_paypal_sync.py`; web `components/invoices/PayPalSync.tsx` | `tests/test_paypal_sync.py` (25) |
| VAT chosen by the owner on a sale with no invoice | `app/paypal_sync.py` | `tests/test_paypal_sync.py` |
| Tie-out: PayPal's balance (Balances API, with its refresh time) vs 1240 PayPal clearing, difference explained | `GET /payments/paypal/tieout` (`app/paypal_sync.py`, `app/routes_paypal_sync.py`); web `components/invoices/PayPalTieOut.tsx` | `tests/test_paypal_sync.py` |
| Ask about PayPal: "What did PayPal cost me this quarter?" (fee entries, 7900 against 1240 PayPal clearing) and "How much is sitting in PayPal?" (the books' 1240 PayPal clearing balance); figures by code, the model only words them | `app/paypal_assistant.py` | `tests/test_paypal_assistant.py` (15; `test_paypal_fees_by_code`, `test_money_sitting_in_paypal_is_the_clearing_balance`) |
| Bill pay by PayPal Payouts, owner-approved, on or after the due date; idempotent `sender_batch_id` | `app/billpay.py`, `app/routes_billpay.py`; web `components/trade/BillPay.tsx` (on `/purchases`) | `tests/test_billpay.py` (24; `test_duplicate_sender_batch_id_recovers_original`); a sandbox payout to a registered account reached SUCCESS on 11 Nov 2026 (table below) |
| Disputes: evidence pack from the books, figures and dates checked by code, sent only on approval | `app/paypal_disputes.py`, `app/routes_paypal_disputes.py`; web `components/invoices/Disputes.tsx` | `tests/test_paypal_disputes.py` (16; e.g. `test_build_then_send_only_with_a_yes`, `test_the_models_words_are_replaced_when_a_check_fails`, `test_the_demo_shows_a_sample_dispute_and_sends_nothing`) |
| Real-sandbox smoke run of the same client code | `tools/payments_sandbox_smoke.py` | Run by the owner on 11 Nov 2026 (table below) |

## What has met PayPal's real sandbox (from `docs/HONESTY.md`, 11 Nov 2026)

GB sandbox business account, direct mode (`PAYPAL_DIRECT=1`: the server's own sandbox REST app; refuses live
credentials).

| Call | Real sandbox | Notes |
|---|---|---|
| OAuth token, Invoicing v2 create / send / read (GBP) | Run | Create answers 201 with only a `self` link; the id is read from it (fixed) |
| Transaction Search `GET /v1/reporting/transactions` | Run | `+0000` dates accepted; opening balance (T1900) listed and not posted |
| Balances `GET /v1/reporting/balances` | Run | Used by the tie-out; PayPal's figure lags (seen ~1.5 h) and is shown with its time |
| Payouts `POST /v1/payments/payouts`, batch read, reused `sender_batch_id` | Run (£1 to an unregistered email: PENDING/UNCLAIMED; 11 Nov 2026, to a registered sandbox personal account: PENDING → PROCESSING → SUCCESS in about 30 s, PayPal's fee £0.02) | The duplicate refusal links the original batch inside `details[].link` (fixed) |
| Invoicing `/remind`, itemised invoices with invoicer details, Disputes (all calls), capture read for the fee | Not run | Fakes only |
| Partner mode (`PayPal-Auth-Assertion`, partner referrals) | Not run | Needs PayPal partner approval |

## Limits you will see

- **Reporting delay:** Transaction Search lists a payment up to **3 hours** after it happens (PayPal's documented
  delay), so a sync straight after a payment can show nothing yet. The tie-out shows PayPal's balance with the time
  PayPal last refreshed it.
- **Payouts are not future-dated in PayPal:** a bill is paid the next time Accnomos is open on or after its due date
  (no scheduler; writing to the books needs the owner's sign-in). A payout waiting at PayPal is followed only on those
  visits. Due dates are the contact's terms, else 30 days.
- **Only PayPal's SUCCESS posts** a bill payment (Dr 2100 Creditors / Cr 1240 PayPal clearing, plus PayPal's payout fee).
  UNCLAIMED money is not posted until claimed; a payout later RETURNED or REVERSED is not reversed by code.
- **Demo:** with no PayPal connected, Sync PayPal reads a fixed sample history labelled on the page (not PayPal data),
  and the disputes panel shows one SAMPLE dispute built by code that is never sent to PayPal. In direct mode every demo
  visitor's PayPal links pay into the one Accnomos sandbox business account.
- **No webhooks:** payments are found when the owner opens Invoices or presses Sync PayPal, and nothing posts until
  they approve.
- **Ask's PayPal answers are books figures:** "How much is in PayPal?" is the books' 1240 PayPal clearing balance (what
  Sync PayPal and approved payments put there), not a live call to PayPal; the tie-out is the screen that reads
  PayPal's own balance.
- **Not handled:** payouts in another currency, PayPal balances used for refunds or chargebacks, and reserves: those
  leave a clearing balance the owner journals by hand.

## Where the AI is, and is not

The AI codes a PayPal purchase to an account (after the owner's own rules and the bank rules; at most 12 calls a sync)
words the answer to a PayPal question in Ask (the figure is code's, from the books), and drafts a dispute response, which code checks (figures, dates, invoice number, no links) and replaces with a
code-written response if a check fails. Amounts, fees, VAT and journals are worked out by code in integer pence. Every
PayPal transaction, payout and dispute response waits for the owner's approval.

## Branch note

The video and these texts describe `paypal-wave3` (which now includes the trust fixes: tie-out, VAT choice on
unmatched sales, duplicate payout recognised from the sandbox's answer) plus `paypal-default` (PayPal first, Stripe
hidden). The upcoming PayPal payments list with its calendar export is on `billpay-schedule` (commit `3dfb7b39`) until
merged.
