# PayPal AI Hackathon video: research behind the v6 cut (12 Nov 2026)

Half an hour of web research before re-cutting the video, on two questions: how strong short demo videos are built,
and what UK small-business bookkeeping apps do with PayPal and AI. Pages were read on 11–12 Nov 2026 through a fetch
tool that summarises them, so the notes below are paraphrases, not quotations; open the link before relying on a detail.

## 1. How a three-minute demo video is built

| # | Finding | What v6 does with it | Source |
|---|---|---|---|
| 1 | Judges may only be required to watch three minutes, so the hook and the proof belong early (the setup and the need in the first 15–20 s). | The presenter's one sentence and the one-line problem are over by 0:16; the app is on screen from the first frame. | RevenueCat, "How to win Shipaton part 4: pitching your app" — https://www.revenuecat.com/blog/engineering/how-to-win-shipaton-part-4-pitching-your-app |
| 2 | A common split for three minutes: about 20 s problem, 20 s what you built, roughly 1:50 of demo (called the most important part), 20 s tech and impact, 10 s close. | v6: 16 s hook and problem, 1 min 41 s of the app working, 34 s of "what makes it different / everything / built and verified", 8 s close. | Reskilll, "Hackathon Demo and Presentation Tips: How to Pitch in 3 Minutes and Win" — https://blogs.reskilll.com/hackathon-demo-presentation-tips-pitch-3-minutes-win-2026/ |
| 3 | Tell one user's story (need → the app in use → result → the new normal) and narrate what the user achieves; a feature list is the thing to avoid. | The middle is one story, "a week in the books": receipt → bank → invoice → paid through PayPal → sync → tie-out → bills → dispute → ask → VAT → reports → files. The feature list comes after it, on slides. | RevenueCat (as above) |
| 4 | Show the project straight away, keep it short, and keep the sound clean; check the rules first so nothing disqualifies the entry. | No title card or long intro; voice-over at one level with room left for a quiet music bed; no third-party logos or product names on screen. | Hackathon.com, "Creating the best demo video for a hackathon" — https://tips.hackathon.com/article/creating-the-best-demo-video-for-a-hackathon-what-to-know |
| 5 | Realistic data, the real device, no half-built features, and a clear ending (a call to action, then stop). | Fictional but realistic books; the Android app beside the web; Jobs dropped from the footage because the shot showed nothing happening; the end card is the call to action (accnomos.com, Try the demo, no sign-in). | Reskilll and RevenueCat (as above) |

Presentation basics applied on top (general practice, not from one source): one idea per shot, a caption that names the
API while the voice says what the user gets, points on a slide appearing one at a time, short sentences, and a little
humour in the voice ("Busy week?", "Hands full?").

## 2. What bookkeeping apps do with PayPal and AI

No product is named on screen or in the narration (the video rules ban third-party trademarks). The notes below name
them only so the wording of the "What makes Accnomos different" slide can be checked.

| Finding | Source |
|---|---|
| A PayPal feed is a standard feature. One UK product's help page describes importing PayPal transactions into a bank account per currency, marking its own invoices paid when PayPal reports the payment, and a rule-based "Guess" for explaining lines; refunds have to be made in PayPal itself, and that page says nothing about paying suppliers or disputes. | FreeAgent support, "Set up a PayPal integration" — https://support.freeagent.com/hc/en-gb/articles/22011654603282 |
| Another vendor's PayPal app (US help page) brings every balance-affecting transaction into a review list about every three hours, with the fee added when a sale is matched; the page lists no multi-currency support and does not cover disputes or payouts. | QuickBooks help, "Connect to PayPal FAQ" — https://quickbooks.intuit.com/learn-support/en-us/help-article/bank-feeds/connect-paypal-faq/L1Np0fQ5E_US_en_US |
| A third product's native PayPal feed is described by an add-on vendor (not a neutral source) as one bank line per movement, with gross and fee on separate lines and each line needing its own reconciliation click. | A2X, "PayPal Xero integration" — https://www.a2xaccounting.com/ecommerce-accounting-hub/paypal-xero-integration |
| AI is already mainstream in UK accounting software: assistants that draft invoices, reconcile, chase payments and read receipts. The same article reminds owners that the taxpayer stays responsible for what the AI categorises, and recalls one assistant being taken offline in January 2025 after showing other businesses' invoice data. | THP Chartered Accountants, "AI in accounting software: what it means for your tax records" — https://www.thp.co.uk/ai-in-accounting-software-what-it-means-for-your-tax-records/ |

### What this means for the slide

- **Not claimed:** that others lack a PayPal feed, receipt reading, an AI assistant, or review before posting. They have them.
- **No "nobody else" claim is made at all.** The help pages above do not mention supplier payouts or dispute evidence,
  but silence on a help page is not proof that a product lacks a feature, and we did not survey the market. The slide is
  therefore titled "What makes Accnomos different" and lists what Accnomos does, each point taken from `README.md` and
  `docs/HONESTY.md`:
  1. The books are files in the user's own OneDrive or Google Drive; there is no Accnomos database.
  2. The AI proposes, code calculates in pence, the owner approves every posting; an audit trail records it.
  3. AI search across the books and PayPal, with figures found by code.
  4. Supplier bills paid by PayPal payout after approval; a retry reuses the batch id, so it cannot pay twice.
  5. Dispute evidence built from the books (a SAMPLE dispute in the demo; the Disputes calls are tested on fakes only).
  6. Hands-free voice: ask aloud, hear the answer, approve a card with a spoken yes.
  7. Local mode: the AI can run on the machine that runs Accnomos.
- **"Built and verified" slide:** five PayPal APIs are in the product; four (Invoicing v2, Transaction Search, Balances,
  Payouts) were run against PayPal's real sandbox on 11 Nov 2026 (`docs/HONESTY.md`). Disputes is marked "Sample in the
  demo", and the narration says "four of them run against PayPal's real sandbox". The test figure is the runtime's
  run of 11 Nov 2026 (4,005 passed).
