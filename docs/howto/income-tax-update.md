# Income Tax quarterly update (sole trader or landlord)

Who this is for: a sole trader or landlord sending Making Tax Digital for
Income Tax updates. Standard quarterly deadlines are 7 August, 7 November,
7 February and 7 May, with Self Assessment on 31 January.

Making Tax Digital for Income Tax is mandatory from 6 April 2026 for
qualifying income over £50,000, from 6 April 2027 over £30,000 and from
6 April 2028 over £20,000. HMRC has no web form and no free software for
quarterly updates: they go through HMRC-recognised MTD software or bridging
software. Filing to HMRC from Accnomos is planned; HMRC isn't issuing
production credentials for new 2026-27 quarterly-update products, so
Accnomos gives you the figures as files to upload (**File it yourself**,
below), and the Connect to HMRC card only practises on HMRC's sandbox.

1. Open **Settings › Business** (`/settings`) and switch on **I am
   self-employed**. Landlords also tick **I let property (landlord mode)**
   further down. Each adds its page to the menu under **Tax**.
   ![Settings, Business: the I am self-employed switch outlined, between the VAT quarters and the VAT scheme choice.](img/income-tax-update-1.png)
   If this goes wrong: the page does not appear in the menu, so reload; the
   switches are saved in your books.
2. Landlords: open **Property** (`/property`), pick the tax year and add each
   property once (name, postcode, how it is let, who owns it, furnished or
   holiday let). Rent and costs are then split by property and by owner in
   HMRC's UK property categories.
   ![Property for 2026 to 2027: Your properties with Add a property open, the name, postcode, how it is let and who owns it, Furnished and Holiday let, and Add property.](img/income-tax-update-2.png)
   If this goes wrong: rent is missing from a property, so check the bank
   line or receipt is approved and tagged to it.
3. Open **Self-employment** (`/self-employment`). To file for real, go to
   **File it yourself** below. To practise, press **Connect to HMRC for Income
   Tax (sandbox)** and sign in with an HMRC sandbox test user to see its
   obligations (this card is not shown once the server files VAT to HMRC's
   live service).
   ![Self-employment (MTD Income Tax): Making Tax Digital for Income Tax, Sandbox · test data only, and the Connect to HMRC for Income Tax (sandbox) button outlined.](img/income-tax-update-3.png)
   If this goes wrong: the connection asks for a live account, so stop: this
   flow works in HMRC's sandbox only.
4. Check the period's turnover and expense boxes. Each figure is worked out
   by code from your approved entries and opens the ledger lines behind it.
   If this goes wrong: a box misses a payment, so check the accounting basis
   in **Settings › Business**: cash counts payments, traditional counts
   invoices.
5. Tick to confirm and send the cumulative period summary. The receipt is
   saved in your books folder.
6. Read HMRC's tax calculation as HMRC's figures: anything HMRC leaves out
   shows as a dash, nothing is estimated in its place.

## File it yourself

At the bottom of **Self-employment**:

- **Quarterly update figures**: pick the tax year and the quarter. The file
  (CSV or XLSX, or saved in `07 Reports`) holds the figures from 6 April to
  the end of that quarter, because every update is cumulative and replaces
  the one before. Column A is HMRC's field name (`periodIncome.turnover`,
  `periodExpenses.costOfGoods`, `periodDisallowableExpenses.…Disallowable`),
  column B the value, column D the SA103F box it ends up in. Row 36 is
  `consolidatedExpenses`, one figure for all allowable expenses, which you
  may send instead of the itemised ones when turnover is under £90,000; the
  file says whether you qualify. Upload it into your MTD or bridging software
  rather than retyping it.
- **Self Assessment self-employment pages**: if you're not in MTD for Income
  Tax, you can still type your return into HMRC's online Self Assessment.
  The file lists each box of the SA103S (turnover under £90,000) or SA103F,
  chosen by turnover, with **Short** and **Full** to choose yourself. Column C
  is pounds and pence, column D whole pounds; totals add up from the boxes.
  Capital allowances, own use and tax adjustments are left for you to fill in.

The quarterly deadlines are on Home's **Deadlines** card and can go into your
calendar (see [Calendar and deadlines](calendar.md)).

## On Android

Income Tax updates are done on the web. The phone shows the deadlines on Home
and in the Talk assistant's answers.
