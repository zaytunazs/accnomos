# Chat and voice actions

"Send a £100 invoice to JM Trading for this month's work" → a card → **Approve** → done.

Ask (`POST /books/ask`, and `/books/ask/voice` after transcription) can answer with a **proposed action**
instead of a facts answer. Nothing happens until the user approves it with `POST /actions/approve`.
Code: `services/runtime/app/actions.py`, `routes_actions.py`; web `apps/web/src/components/ask/ActionCard.tsx`;
mobile `apps/mobile/lib/screens/ask_screen.dart`.

## Who decides what

| Step | Decided by | How |
|---|---|---|
| Is this an instruction at all? | code, then the model | Code only asks the model if the message has an action word (invoice, send, chase, log, miles, hours…) and doesn't start like a question ("how", "what", "did"…). The model then returns `kind`: `create_invoice`, `chase_invoice`, `log_mileage`, `log_timesheet`, `pay_overtime`, `create_quote`, `convert_quote_to_invoice`, `remind_unpaid`, `payment_link_message` or `none`. `none`, or a reply in the wrong shape, means an ordinary Ask answer. |
| Names (customer, job, staff, vehicle, invoice) | the model **quotes**, code **finds** | The model copies the words the user used ("JM Trading"). Code matches them against the user's own lists: contacts (customers only), open jobs, active staff, active vehicles, unpaid invoices. It uses `difflib` ≥ 0.8 on normalised names ("J.M. Trading Ltd" = "JM Trading"), also against runs of whole words, so "Alex" finds Alex Green and "Oak Lane" finds "Bathroom, 4 Oak Lane". If two names match about equally, or none does, Ask asks which one and lists the candidates. The lists never go to the model. |
| Amounts, hours, miles | the model **quotes**, code **parses** | The model returns the text as said (`"£1,250.50"`, `"7.5"`). Code parses it, and **refuses any figure that isn't in the user's message**, so a made-up amount becomes a "How much?" question. Hours round to the nearest quarter (as on timesheets), miles to 0.1. |
| Dates | the model **quotes**, code **parses** | "yesterday", "Monday", "3 Oct", "3/10" → a date (a day with no year is the latest one not after today). Future dates are refused. |
| VAT code | code | The user's own words if they named one (the model passes it on). Otherwise S (20%) if the invoice profile has a VAT number, or O (no VAT) with a warning if it doesn't. |
| Net, VAT, totals | code | Per line: net = quantity × unit price, VAT = net × rate, each rounded half up to the penny (the same rules as `app/invoicing.py`). "Including VAT" amounts are split so that net + VAT is exactly the amount where possible. The invoice module re-prices on approval and refuses if the totals differ. |
| "this month's work" | code, words only | It becomes "Work for October 2026" in the description. No hours or dates are looked up. |
| Due date | code | The user's terms if they said them, otherwise the invoice profile's, otherwise 30 days. |
| Send or draft | the user's words, then code | `send: true` only if the user asked to send or email it, and only if the customer has an email address in contacts. Otherwise it's a draft, and the card says so. |
| Reminder wording (chase) | the model, checked by code | Written when the card is made (`app/ai/remind.py`, figures checked against the invoice), so the user sees the exact email before approving. |
| Doing it | the user | **Approve** runs it once. *Reject* records the no. *Change* puts the question back in the box to reword (web). |

## No server state

The runtime keeps nothing between Ask and Approve. The proposal (`id, kind, summary_md, preview, confirm_text,
created_at, expires_at`) goes to the app, and the app posts it back unchanged. It carries
`signature = HMAC-SHA256(key, canonical JSON of everything else)` with
`key = HMAC-SHA256(ACTIONS_SIGNING_KEY, SHA-256(Graph token))`. So:

- a changed amount, recipient, line or expiry fails the check (403);
- a proposal posted with another sign-in's token fails the check (403);
- a proposal older than 15 minutes is refused (410).

`ACTIONS_SIGNING_KEY` is an environment variable on the runtime. Without one, each runtime process makes a
random key at start-up, which is fine for one process. With several replicas, set the same key on all of them,
or proposals made on one replica fail on another. The token hash alone would not be enough: the app holds the
token, so it could compute the key.

The app must approve with the **same Graph token** it asked with. MSAL normally returns the cached token for
the whole hour; if the token is refreshed between Ask and Approve, the user has to ask again.

## Once only

Approving first appends an `approving` line to `_System/audit/actions/<yyyy-mm>.jsonl` (the month the action
was proposed), using the same If-Match read-modify-write as every other file (create-only when the month's file
does not exist yet, so two approvals at the same moment cannot both "create" it). Then it runs the action and
appends `executed` with the result. Approving again returns the first result (`status: already_done`) and does
nothing; a second approval racing the first gets a 409. If running fails, a `failed` line is written and the user
can try again. If the runtime dies between `approving` and `executed`, the action is never run again on its own,
because it may have half run (an email may have gone). For 10 minutes (`APPROVING_STALE`) approving answers
"already being approved"; after that it says the earlier approval did not finish. The user checks the timesheet,
mileage log or invoice, then rejects the card (`POST /actions/reject` with the same card, the Reject button),
which writes a `rejected` line with `cleared: "stale approving"`, and asks again if it is still needed. The web action
card adds what to do under each message, naming where to check (Invoices, the job's timesheet, the mileage log): wait
10 minutes before approving again, or, once stale, check, Reject, and ask again. A timesheet entry's id is the first 12
characters of the action id, so it can be traced back to the audit line. A rejected action can't be approved,
and an approved one can't be rejected.

If an invoice is created but sending it fails (no `Mail.Send` consent yet, a Graph error), the result says
*saved as a draft but not sent*. The user sends it from Invoices, and approving again does not create a
second invoice.

## What each action does on Approve

| Kind | Runs | Available |
|---|---|---|
| `log_timesheet` | `jobs.add_entry` (job must be open, staff must exist; a closed job gets "reopen it on Jobs" rather than "couldn't find"). Hours with overtime in them ("add 2 hours for Ellie on the kitchen job, including 1 hour overtime at double rate") are one card with two lines: code reads the overtime hours and the rate words from the user's own sentence (the model only says it is a timesheet, even if it read it as `pay_overtime`), prices each line from the staff member's hourly rate in pence (quarter hours, half up), and on Approve adds two entries, the overtime one with `rate_multiplier` set. Such a card changes pay, so it is tap-only (`needs_tap`); plain hours may still be approved by voice | now |
| `pay_overtime` | `jobs.set_rate_multiplier` on exactly the entries the card listed (refused if their hours changed or an approved pay run already paid them). The model only copies the rate words ("double", "time and a half") and the week ("last week"); code reads them, finds the person's entries for that week (and job, if named) and prices them from the payroll hourly rate. The next pay run pays them; the card notes that regular overtime can affect holiday pay (check with your adviser) | now |
| `create_invoice` | `invoicing.create_invoice` → PDF (`app/pdf.py`) → `invoicing.send_invoice` through Graph if `send` | on `main` (`app/invoicing.py`) |
| `chase_invoice` | `invoicing.send_reminder` with the reminder shown on the card and the sent PDF attached | on `main` |
| `log_mileage` | `mileage.add_entry(books, MileageEntry, user)` | on `main` (`app/mileage.py`) |
| `match_bank_line` | `Books.confirm_match(line_id, event_ids, user)`: the same as confirming a suggested match on Bank; matching posts nothing, and a line or entry that changed since is refused (409) | month-end close only |
| `close_month` | `month_end.lock`: recomputes the month's snapshot and refuses (409) if its hash differs from the card's, then saves `07 Reports/<yyyy-mm>-month-end.xlsx`, appends a close record to `_System/close/<yyyy-mm>.json` and audits `month_closed` / `month_reclosed` | month-end close only |
| `create_quote` | `quotes.create_quote`: priced like an invoice by the same code, saved as a **draft**; never emailed from Ask (sending is the Quotes page, with its own tick). "Valid for 14 days" is the only figure it reads beyond the amount. | now |
| `convert_quote_to_invoice` | `quotes.convert_to_invoice`: a draft invoice with the quote's lines and totals exactly. The quote is found by number ("QU-0003", "quote 3") or by customer; several open quotes for a customer means a question (an accepted one wins if only one is). Refused at Approve if the quote changed or was already converted. | now |
| `remind_unpaid` | `paypal_assistant.run_remind`: for each invoice on the card, checked again first (still unpaid, same PayPal invoice), PayPal's own reminder (`POST /v2/invoicing/invoices/{id}/remind`) when its Pay online link is a PayPal invoice on the connected account, otherwise the reminder email shown on the card (`invoicing.send_reminder`). One that fails does not stop the rest; the result names it. Tap only | now |
| `payment_link_message` | `paypal_assistant.run_message`: adds a Pay online link first if the card said so (`online_payments.add_link`, PayPal first), then returns the message with the link added by code, a `wa.me` link and an `sms:` link. Nothing is sent: the user sends it from their own phone | now |

Questions about quotes ("any outstanding quotes?") are not actions: they are answered from the quote facts in the Ask pack (`quotes` in `app/facts.py`: waiting for an answer, expiring within 7 days, expired, accepted and not yet invoiced, drafts), worked out by `quotes.quote_facts` and checked by the same number check as every other answer.

## PayPal: talk to your accountant

`app/paypal_assistant.py`. Typed in Ask or spoken to the assistant (speech-to-text, then exactly the same path as typed
text, `routes_ask.ask_voice`); the web's empty Ask thread offers the first three as chips.

| Say | What happens |
|---|---|
| "Send a PayPal reminder to everyone who owes me" | `remind_unpaid` card: every overdue unpaid invoice (oldest first, at most 10), who, how much (what is still owed, in pence, after part payments and credit notes), how many days overdue, and how each goes: **PayPal reminder** when the invoice's Pay online link is a PayPal invoice on the connected account and the customer has an email address, otherwise the usual **email reminder** (`app/ai/remind.py`, checked by code). Not-yet-due invoices are left out and the card says how many. |
| "Remind JM Trading through PayPal" | the same card for that customer's unpaid invoices (due or not). A chase that mentions PayPal or "everyone" is turned into this card by code (`paypal_assistant.reroute`), whatever kind the model picked. |
| "WhatsApp JM Trading the payment link", "text Hartley the pay link for INV-0003" | `payment_link_message` card: the message, who it is for, the amount, and which link goes with it. On Approve: the text with the link, **Copy message**, **Open in WhatsApp** (`https://wa.me/<number>?text=`) and **Open in Messages** (`sms:<number>?&body=`). The number is the contact's phone, as `44…`; without one the links open the app with no chat picked. |
| "Who owes me money?" | the aged balances answer (`ask_more.owed_answer`) plus, by code, how many of the unpaid invoices have a PayPal link and how many have no payment link. |
| "What did PayPal cost me this quarter?" | code adds up the PayPal fee entries in the span (7900 Bank charges in entries against 1240 PayPal clearing, or with PayPal as the counterparty; reversals net off): the fees, the number of fee entries, what came in through PayPal and the fee as a percentage of it (one decimal, half up). "This quarter" is the calendar quarter so far; other spans as for profit questions (`ask_router.pnl_span`). With no fee entries it says so, in code's words. |
| "How much is sitting in PayPal?" | `online_payments.clearing_balance(books, "paypal")`: the 1240 PayPal clearing balance by the books (payments approved, less fees, less payouts matched to the bank), the last payout, and what is owed on unpaid invoices with a PayPal link. It is the books' figure, not PayPal's live balance, and the answer says so. |

Words and figures: the model may word the answers and the payment message; code checks them as everywhere else (every
figure must be in the facts, `ai/ask.py KnownNumbers`; the message must quote the invoice number and the amount exactly
and contain no link or web address). Anything that fails is replaced by code's own words, with the reason on the card.
The link itself is always added by code after the check, at approval.

PayPal calls: the runtime calls PayPal's REST endpoints itself (`app/payment_providers.py`, `PayPalApi.remind_invoice`),
with the same token cache, partner `PayPal-Auth-Assertion` (or none in direct sandbox
mode), test transport and error handling as the payment links. Invoicing v2 `remind` (schema checked 11 Nov 2026):
body `{"send_to_recipient": true, "send_to_invoicer": false}`, answer 204; PayPal documents that a caller's `subject` and
`note` are not honoured, so none are sent and the card says "PayPal reminder" rather than showing an email.
UNVERIFIED against the live sandbox (no sandbox credentials on the build machine): that `remind` accepts an invoice we
sent with `send_to_recipient: false`, and that PayPal emails the address on the PayPal invoice (the customer's email when
the link was made). The unit tests check the request field by field against a mock; `app/online_fakes.py` answers it in
test mode.

**PayPal Agent Toolkit: not used, on purpose.** Checked `paypal-agent-toolkit` 1.11.0 from PyPI (the wheel's source,
github.com/paypal/agent-toolkit) on 11 Nov 2026. It does have `send_invoice_reminder`, but in-process use here is
impractical: the package pins `openai-agents==0.0.2`, `langchain==0.3.23` and `crewai-tools==0.13.2` as install
requirements; its `PayPalClient` uses blocking `requests` with the base URL fixed to PayPal's sandbox or live constants
(no transport to inject, so neither the test fakes nor test mode could see the calls); it fetches a new OAuth token on
every request; it sends no `PayPal-Request-Id` and no `PayPal-Auth-Assertion` (its `Context.merchant_id` is stored but
never used), so it cannot act for an onboarded merchant; its reminder handler posts the invoice id in the body and
`print`s the URL and PayPal's response to stdout; and it has no capture-refund tool. The runtime therefore calls the same
PayPal REST endpoints directly, behind the same approve card, and makes no claim to use the toolkit.

**Refunds: not built.** Refunding a captured PayPal payment (`POST /v2/payments/captures/{id}/refund`) would need the
capture id of an invoice payment, which is still UNVERIFIED (see `payment_providers.py`), and a reversing entry whose
treatment (re-open the debt, or a credit note) is the user's decision. Without a tested path it is left out rather than
offered.

## Cards from the month-end close

The month-end close (`app/month_end.py`, `docs/ARCHITECTURE.md` "The month-end close") makes cards with the same
`Draft` → `new_action` → signature as Ask, so they go through the same `POST /actions/approve` and `/actions/reject`, are
executed once and expire after 15 minutes. Ask never proposes `match_bank_line` or `close_month`; the model plays no
part in them (the match is `Books.bank_suggestions`, code; the close figures are the snapshot). Reminder cards are
`chase_invoice` cards built by `actions.chase_draft`, shared with Ask; with no AI set up, code writes the reminder. The
cards are not stored: `_System/close/<yyyy-mm>.json` keeps each card's id, kind and summary, so an expired or reloaded
card is renewed by running the close again. A rejected close card changes nothing.

Feature checks are still done at runtime (`actions.invoicing()`, `actions.mileage()`); both modules are on `main`, so
they pass. If one were missing, Ask would say plainly that it can't do that yet and never show a card it couldn't carry out.

## Not built

- Invoices from timesheet hours ("invoice JM for the Elm Road hours"): the model only takes amounts or lines
  the user says.
- Editing a proposal in place: *Change* means asking again.
- Requesting `Mail.Send` consent from the card. Until the invoicing UI has asked for it once, a "send" ends as
  a draft with the reason given.
