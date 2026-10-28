# Review: Sales and Purchases gaps against Xero

Branch `claude/sales-purchases`. Not pushed.

## What changed

Runtime (`services/runtime/app`), all money in integer pence, all figures by code:

| Area | Files | Routes |
| --- | --- | --- |
| Products and services (code, name, description, sale and purchase price, VAT rate, income and expense account; CSV import/export incl. Xero headers) | `items.py`, `routes_items.py`, `numbering.py` | `/items`, `/items/export`, `/items/import`, `/items/{code}/line` |
| Quotes QU-0001: draft, sent (PDF + Outlook behind `confirm`), accepted/declined/expired, convert to invoice | `quotes.py`, `routes_quotes.py`, `pdf_docs.py` | `/quotes/*` |
| Purchase orders PO-0001: draft, approved, sent, convert to bill (a proposal in Review), match a received bill | `purchase_orders.py`, `bills.py`, `routes_purchase_orders.py` | `/purchase-orders/*` |
| Repeating invoices and bills (weekly/monthly/quarterly/yearly, end date, approve automatically) | `repeating.py`, `routes_repeating.py` | `/repeating/*` |
| Sales and Purchases overviews | `overview.py`, `routes_overview.py` | `/sales/overview`, `/purchases/overview` |
| Customer statements (PDF and email) | `statements.py`, `routes_overview.py` | `/statements/{contact_id}`, `/pdf`, `/send` |

Also: `LineIn.item_code`, `Invoice.repeating`, audit summaries for every new action (`audit_view.py`), new folders in `paths.py`, `docs/HONESTY.md` section.

Web (`apps/web`): item picker on invoice lines, shared components in `src/components/trade/`, runtime types and calls in `src/lib/runtime.ts`, pages in `e2e/pages.ts` so the phone and axe specs cover them.

## Routes for the menu (another agent is redesigning the top menu)

| Route | Page |
| --- | --- |
| `/sales` | Sales overview, customer statements |
| `/sales/quotes` | Quotes |
| `/sales/items` | Products and services (also the catalogue for purchases) |
| `/sales/repeating` | Repeating invoices and bills |
| `/purchases` | Purchases overview |
| `/purchases/orders` | Purchase orders |

No existing nav entry was changed. The pages link to each other and to `/invoices`, `/review` and `/contacts`.

## How the rules are kept

- Every send (quote, order, statement, and an invoice made by an approve-automatically schedule) uses the user's Outlook; the three sends the user clicks need `confirm: true` from a ticked box, tested to refuse without it.
- Nothing posts without the user: a bill from an order waits in Review. The one exception is the explicit, worded "Approve automatically" tick on a repeating item, which is audited as `repeating:<id>`.
- No user database: new files are under `_System/Items`, `_System/PurchaseOrders`, `_System/Repeating`, `_System/Invoicing/quote_sequence.json`, `03 Sales/quotes` and `03 Sales/statements`.
- Repeating runs when Sales, Purchases or Repeating opens, or on `POST /repeating/process`. No background server. Documented in `docs/HONESTY.md` and on the page.

## Tests

- Runtime: `test_items` 12, `test_quotes` 15, `test_purchase_orders` 18, `test_repeating` 18, `test_overview` 13 (76 new). They cover conversion keeping lines, VAT and totals exactly, numbering, month-end schedule dates, idempotent repeating, send refused without confirm, statement and overview figures.
- E2E: `e2e/sales-purchases.spec.ts` (4 flows: item to quote to invoice; order to bill in Review; repeating makes drafts on page open; overview and statement email), plus the six new pages in `e2e/pages.ts` for the phone and axe specs.
- Gate results are at the bottom of this file.

## Risks

- Item income account is stored but invoices still post to 4000 Sales. One expense account per bill.
- Quote and order conversion are two writes; a crash between can leave an orphan draft (documented).
- Repeating with approve automatically sends real email on a page visit. If the mailbox token lacks `Mail.Send` the invoice stays a draft. The web only asks for mail consent on a visit when a due invoice is set to approve automatically.
- Matching a received bill to an order is by the user's choice, with no automatic suggestion in Review.
- Overview "money in/out" depends on payments being recorded or matched.
- Not run against real Outlook, Graph or a real Xero CSV; fake storage and fake mailbox only. Meta and Baseten were not called.
