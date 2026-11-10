# Connect eBay: setting it up

Connect eBay lets a UK seller sign in with their eBay account so Accnomos fetches their sales, refunds, fees, postage
labels and payouts. Each one becomes a **proposal on Review**; nothing is posted until the user approves it. The code
is `services/runtime/app/ebay.py` (eBay's API), `services/runtime/app/ebay_sync.py` (mapping, dedupe, storage),
`services/runtime/app/routes_ebay.py` (routes), `services/runtime/app/ebay_fakes.py` (test-mode fakes) and
`apps/web/src/components/bank/EbayConnect.tsx` (the card on the Bank page, shown only when the server is set up).

Sources were read on 9 Nov 2026. eBay moved its developer pages to `developer.ebay.com/develop/...` during 2026; many
old `api-docs/static/...` links now redirect.

## What it fetches, and what it doesn't

**Fetches** (eBay Finances API, sellers on managed payments), up to 730 days back (90 by default): sales, refunds,
selling fees (final value, per order, international, regulatory, store, insertion and the rest), advertising fees
(Promoted Listings: AD_FEE, PREMIUM_AD_FEES, offsite ads), postage labels bought on eBay and payouts to the bank, plus
item titles for the orders (Fulfillment API). Each becomes a proposal on Review; payouts are matched on the bank line.

**Does not fetch** eBay's monthly invoice for its fees, which is the document that supports reclaiming the VAT on
them. Download it yourself: Seller Hub › Payments › Reports › Invoices, "Summary Download" or "Detail Download" for
the month (eBay help, "Reconciling your eBay sales transactions",
https://www.ebay.co.uk/help/fees-billing/sell-fees-payments/reconciling-ebay-sales-transactions?id=4847, read 10 Nov
2026), and keep it with your records (or drop it in the Inbox).

**Does not create** invoices for buyers. eBay can generate a VAT invoice per order for business sellers, from the
order's "View order details" page in Seller Hub (eBay Seller Centre, "VAT invoices", April 2025,
https://www.ebay.co.uk/sellercentre/news/2025-april/vat-invoices).

Also not imported, listed after each sync to book by hand: CREDIT, ADJUSTMENT, DISPUTE, TRANSFER, WITHDRAWAL,
LOAN_REPAYMENT and PURCHASE transactions, and anything not in GBP.

## 1. Keyset

1. Join the eBay Developers Program and create an application keyset (one for **Sandbox**, one for **Production**).
   Each gives an App ID (client id) and a Cert ID (client secret).
2. Production keysets stay inactive until the app has subscribed to, or been exempted from, **marketplace account
   deletion notifications** (section 6).

## 2. RuName (the redirect)

eBay's OAuth does not take a URL as `redirect_uri`; it takes the app's **RuName**, configured under *User Tokens →
Get a Token from eBay via Your Application* (https://developer.ebay.com/develop/guides/authorization.md, "Getting your
RuName values"). There is one RuName per environment. Fill in:

| Field | Value |
|---|---|
| Display title | Accnomos |
| Privacy policy URL | the public privacy policy page on the web app |
| **Auth Accepted URL** | `https://<runtime host>/books/ebay/callback` (this runtime's callback) |
| Auth Declined URL | `https://<web host>/bank#feed=ebay&error=access_denied` |

The callback checks the signed `state` and forwards `code` and `state` to the Bank page in the URL fragment; the
page posts them back with the user's own token, and only then is the code exchanged.

## 3. Scopes

Requested on the consent page and on every refresh:

- `https://api.ebay.com/oauth/api_scope/sell.finances` (Finances API: transactions, payouts)
- `https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly` (Fulfillment API: order line item titles)

Check both are granted to the keyset in the developer portal ("OAuth Scopes").

## 4. Server environment

| Variable | Value |
|---|---|
| `EBAY_CLIENT_ID` | App ID |
| `EBAY_CLIENT_SECRET` | Cert ID (a secret: the server's environment only, never the repo) |
| `EBAY_RUNAME` | the RuName for the same environment |
| `EBAY_ENV` | `sandbox` (default) or `production` |
| `EBAY_TOKEN_KEY` | 32 random bytes, base64 (`openssl rand -base64 32`); if unset, `BANKFEEDS_TOKEN_KEY` is used |
| `EBAY_DELETION_TOKEN`, `EBAY_DELETION_ENDPOINT` | section 6 |

With any of the first three or the key missing, `GET /books/ebay` answers `configured: false` and the web card is
hidden. Changing the token key makes stored eBay connections unreadable; the card then says "Connect again".

## 5. Sandbox test seller

1. In the developer portal, create a **Sandbox test user** (Sandbox user registration) to sign in with on
   `auth.sandbox.ebay.com`.
2. Sandbox Finances data: eBay's API notes describe Finances data for sellers on eBay's managed payments (assumed,
   not verified, to be every UK seller now). To be checked by the owner: whether the Sandbox test user returns any transactions at all, or only empty answers
   (204). Until then, the flow is proven against the fakes (`services/runtime/tests/test_ebay.py`) and test mode
   (`ACCNOMOS_TEST_MODE=1`, `/__test/ebay/oauth2/authorize` agrees at once).
3. **Unverified hosts:** eBay's Finances spec lists only production servers (`apiz.ebay.com`); the code assumes
   `https://apiz.sandbox.ebay.com/sell/finances/v1` and `https://api.sandbox.ebay.com/sell/fulfillment/v1` for the
   sandbox. The first sandbox sync confirms or refutes this.

## 6. Marketplace account deletion (needed before the first production call)

eBay requires every app to subscribe to marketplace account deletion/closure notifications, or to apply for an
exemption if it does not persist eBay data; the keyset is activated only after that
(https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion).

The runtime answers eBay's challenge at `GET /ebay/account-deletion?challenge_code=…` with
`sha256(challengeCode + verificationToken + endpoint)` and acknowledges notifications with 204. Set
`EBAY_DELETION_TOKEN` (32–80 characters: letters, digits, `_`, `-`) and `EBAY_DELETION_ENDPOINT` (the exact public
HTTPS URL entered in the portal), then enter the same two in the portal's Alerts & Notifications page.

**Owner decision:** the runtime keeps no eBay data, but each user's own books (in their OneDrive) do keep imported
eBay sales and payouts, which the server cannot reach without that user's token. Whether that counts as "persisting
eBay data" for the exemption is for the owner to answer to eBay honestly; subscribing (as built) is the safe choice.

## 7. Managed payments and business accounts

- The Finances API covers sellers on eBay's managed payments. **Unverified:** that every UK seller is on it now;
  an account not on it would get no transactions.
- eBay (UK) Limited adds 20% UK VAT to fees billed to business sellers with a UK address (eBay's announcement of
  1 Aug 2017,
  https://community.ebay.co.uk/t5/Announcements/Changes-to-VAT-on-eBay-fees-for-business-sellers-with-a-UK/ba-p/6241551).
  **Unverified:** whether the Finances API's fee amounts include that VAT, and eBay's VAT number. So fee VAT is only
  proposed as reclaimable when the user types the VAT number from eBay's VAT invoice on the eBay card.

## 8. Rate limits and growth check

- Finances and Fulfillment calls count against the app's daily call limits. A sync makes 1 token refresh, one call
  per 200 transactions, one per 200 payouts and one per 50 new orders. A seller with a few hundred orders a quarter
  needs a handful of calls per sync.
- If the default limits become too low (many users), eBay's **Application Growth Check** raises them; it reviews the
  app's call efficiency. Not needed for a pilot. The growth-check page (`developer.ebay.com/grow/application-growth-check`)
  answered 403 to our fetch on 9 Nov 2026, so its current criteria are unverified.

## 9. What the import does (summary)

| eBay | Proposal (all settle through 1250 eBay clearing) |
|---|---|
| SALE | Sale for `amount + totalFeeAmount` (VAT 20% included when VAT-registered; zero-rated, flagged, if eBay collected tax), plus the fees split by `marketplaceFees[].feeType`: selling fees to 5400 Marketplace fees, advertising fees (AD_FEE, PREMIUM_AD_FEES) to 6210 Marketplace advertising, one line per fee type |
| REFUND | The sale turned round for `amount + totalFeeAmount`, plus fee credits from eBay, split the same way |
| NON_SALE_CHARGE (and FEE) | Selling fee to 5400, or advertising fee to 6210 when `feeType` is AD_FEE / PREMIUM_AD_FEES or the memo names promoted or offsite ads (a credit if `bookingEntry` is CREDIT) |
| SHIPPING_LABEL | Postage (7520), with the VAT eBay reports in `taxes` |
| Payout (SUCCEEDED) | Recorded; on the Bank page "Payout from eBay" on the bank line posts Dr 1200 Bank / Cr 1250 eBay clearing |
| CREDIT, ADJUSTMENT, DISPUTE, TRANSFER, WITHDRAWAL, LOAN_REPAYMENT, PURCHASE | Skipped and listed, to book by hand |

The same VAT rule applies to selling and advertising fees: eBay (UK) Limited adds 20% UK VAT to all fees billed to
UK business sellers (section 7), reclaimable once eBay's VAT number is saved on the card. 1250, 5400 and 6210 are
added to a saved chart of accounts that lacks them; if a code is already used by an account with another name, the
eBay account takes the first free code after it (1251…, 5401…, 6211…) and imports post there.

Every eBay transaction and payout is remembered by id in `_System/eBay/imported.json` in the user's books, and each proposal's id
is derived from the books, the transaction type and id, written create-only: two syncs at once (two tabs, two
devices, a retry) or a sync cut short never propose anything twice, even after a proposal was rejected. Sync reads the last 90 days by default (up to
730 on request). How a payout is worded on a UK bank statement is unverified; a money-in line naming "eBay" gets the
"Looks like a payout from eBay" hint, and any money-in line can be matched as one.

## Owner steps (checklist)

1. Create Sandbox and Production keysets; note App ID and Cert ID.
2. Configure a RuName per environment with the accept URL `https://<runtime>/books/ebay/callback`.
3. Set the env vars in section 4 on the runtime host (Sandbox first).
4. Create a Sandbox test user and run Connect eBay → Sync now; confirm the sandbox hosts and what data comes back.
5. Set up account deletion notifications (section 6) and decide subscribe vs exemption.
6. Switch `EBAY_ENV=production` with the Production keyset and RuName; sync one real account and compare the
   proposals with Seller Hub's payout report and eBay's VAT invoice for fees before relying on it.
