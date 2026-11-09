# Amazon seller data: a plan for later (Selling Partner API)

Research for a "Connect Amazon" like Connect eBay (`docs/EBAY_SETUP.md`). Nothing is built. Read on 9 Nov 2026 on
Amazon's developer documentation (developer-docs.amazon.com, which now redirects to developer-docs.amazon; the pages
carry "updatedAt" dates, quoted below).

## What it would take

### 1. Register as a public developer

Accnomos would be an app other sellers authorise, so it must register as a **public** SP-API developer
(https://developer-docs.amazon.com/sp-api/docs/applying-for-pii-roles, "Register as a Public SP-API Developer"):

- Public developers "obtain explicit authorization from each seller or vendor through OAuth" and "must list their
  application in the Amazon Selling Partner Appstore, in accordance with the Solution Provider Portal Agreement".
- Prerequisites: a public website describing the service (not under construction, not log-in only, HTTPS, privacy
  policy and terms), and the roles chosen up front.
- The developer profile (Solution Provider Portal → Settings → Developer Profile, or Seller Central → Apps and
  Services → Develop Apps) asks for contact details, data access, roles, use cases and **security controls** answered
  against the Acceptable Use Policy (AUP), Data Protection Policy (DPP) and Solution Provider Portal Agreement.
  Amazon's questions come through a case and must be answered within five days or the case is closed.
- Registration must be done by the primary account user
  (https://developer-docs.amazon.com/sp-api/docs/sp-api-registration-overview).

### 2. Roles: no restricted role needed

- `listFinancialEvents` (Finances v0) needs **Finance and Accounting** (or Account Information Service Provider, EU
  only) (https://developer-docs.amazon.com/sp-api/docs/finances-api, updated 9 Sep 2026). The newer
  `listTransactions` (Finances v2024-06-19) needs Finance and Accounting.
- Finance and Accounting is not a restricted role. Restricted roles are those that "require sensitive information,
  which might include personally identifiable information (PII)", e.g. Direct-to-Consumer Shipping and Tax Invoicing
  (https://developer-docs.amazon.com/sp-api/docs/roles-faq). Requesting one adds a two-phase review: business
  verification, then a **data security assessment** of PII data flows, possibly with an architecture review and a
  screen-share demo (the registration page above).
- **Plan:** request Finance and Accounting only. Bookkeeping needs order ids, amounts, fees and payouts, not buyer
  names or addresses, so the PII review is avoided.

### 3. Appstore listing and authorisation limits

- Listing (Solution Provider Portal → app → Create listing) needs the public developer registration, a working OAuth
  flow (Appstore or website authorisation), and AUP/DPP compliance of everything on the website. Listing text must
  not use Amazon trademarks or superlatives
  (https://developer-docs.amazon.com/sp-api/docs/list-your-app-on-the-selling-partner-appstore, updated 2 Nov 2026).
- Listing is optional, but an unlisted public seller app is capped at **25 OAuth authorisations** (listed: unlimited;
  10 self-authorisations for testing either way)
  (https://developer-docs.amazon.com/sp-api/docs/application-authorization-limits, updated 9 Sep 2026). A pilot of
  up to 25 sellers can run before the listing is approved.

### 4. Fees for public apps

Amazon announced SP-API usage and annual fees for third-party developers, then cancelled them: "we have decided that
we will not move forward with the SP-API usage and annual fees at this time"
(https://developer.amazonservices.com/announcement-new-tier-advanced-solution-provider-portal; the page carries no
date; third-party reports place the cancellation in May 2026). **Unverified:** whether any fee applies today; check the
Solution Provider Portal before registering, as "at this time" leaves it open.

### 5. Finances API: `listFinancialEvents`

`GET /finances/v0/financialEvents` (https://developer-docs.amazon.com/sp-api/reference/listfinancialevents, updated
9 Sep 2026):

- Query: `PostedAfter`, `PostedBefore` (ISO 8601; both more than two minutes before the request),
  `MaxResultsPerPage`, `NextToken` (repeat with the same arguments until no `NextToken` comes back).
- "Orders from the last 48 hours might not be included"; deferred events appear only once released.
- Rate: 0.5 requests a second, burst 30.
- Answer: `FinancialEvents` with lists per event type, among them `ShipmentEventList` (a sale: `AmazonOrderId`,
  `PostedDate`, `ShipmentItemList[{SellerSKU, QuantityShipped, ItemChargeList[{ChargeType, ChargeAmount}],
  ItemFeeList[{FeeType, FeeAmount}], ItemTaxWithheldList, PromotionList}]`), `RefundEventList`,
  `ServiceFeeEventList`, `AdjustmentEventList`, `ProductAdsPaymentEventList`, `ChargebackEventList`,
  `GuaranteeClaimEventList` and others (34 lists in the v0 model).
- Payouts: financial event groups (`listFinancialEventGroups`), each a settlement period with its transfer to the bank.

The newer Finances v2024-06-19 (`listTransactions`) is the current version on that page; v0 is listed as legacy but
still documented. A build would start on v2024-06-19 if its transaction shape covers fees and payouts as fully.

### 6. Mapping (same as eBay)

ShipmentEvent → sale gross (item charges incl. VAT; Amazon is the deemed supplier for some overseas sales, which
must not be counted as the seller's output VAT) into an "Amazon clearing" account; ItemFeeList and ServiceFee →
marketplace fees (which Amazon entity bills UK fees, and with what VAT, is unverified and must be researched
separately); RefundEvent → refund; financial event group transfer → payout matched to the bank line. Dedupe by event
identity (order id + posted date + type), as `_System/` ids.

## Owner steps when this is picked up

1. Register as a public developer with the Finance and Accounting role only; prepare the website and security answers.
2. Build against the SP-API sandbox ("Static" sandbox for Finances, per the Finances API page) and test with up to 10
   self-authorisations, then up to 25 sellers unlisted.
3. Submit the Appstore listing.
4. Confirm the current fee position in the Solution Provider Portal.
