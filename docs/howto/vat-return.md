# Do a VAT return

Who this is for: a VAT-registered owner filing through Making Tax Digital.

Filing to HMRC from Accnomos is planned. Until the server is switched to HMRC's
live service, **Connect to HMRC** practises the flow on HMRC's sandbox (its
test service), and you file the real return with **File it yourself** below:
a file you upload to bridging software. The demo always uses the sandbox.

You can't type a VAT return into your HMRC online VAT account: since
1 November 2022 every return goes through Making Tax Digital software or
bridging software, unless HMRC has given you an exemption (VAT Notice 700/22).

1. Open **VAT return** (`/vat`, under **Tax** in the menu) and pick the
   quarter in **VAT period**. Each period shows whether it is open and when it
   is due. The nine boxes are worked out by code from the entries you
   approved, with the number of entries behind each.
   ![Your return for Jul–Sep 2026: the nine boxes, Box 1 £3,857.63 from 9 entries, Box 4 £50.30 from 21, Box 5 net VAT £3,807.33 to pay by 7 Nov.](img/vat-return-1.png)
   If this goes wrong: the periods are the wrong months, so set your VAT
   quarters in **Settings › Business** first.
2. Press **?** beside a box for what it means, or the entries count to see the
   documents behind it.
   ![Box 4, VAT reclaimed on purchases, explained in a side panel: 21 approved entries feed Box 4, with links to see them on Review and in Files.](img/vat-return-2.png)
   If this goes wrong: a figure looks off, so find the entry in Review or
   Bank and undo it; the boxes rebuild.
3. To file the real return now, skip to **File it yourself** below. To
   practise, under **Connect to HMRC** press **Connect to HMRC (sandbox)** (in
   the demo, **Make an HMRC sandbox test user** and then **Connect to HMRC
   sandbox**) and sign in with HMRC's test user. Once the server files to
   HMRC's live service, the button is **Connect to HMRC** and you sign in with
   your own HMRC online services account.
   ![Connect to HMRC in the demo: HMRC sandbox, real test service, no real tax filed, what signing in involves, and the Make an HMRC sandbox test user button outlined.](img/vat-return-3.png)
   If this goes wrong: the sign-in page does not come back, so close it and
   press Connect again; **Settings › Connection** shows whether HMRC is
   connected.
4. Press **Show obligations** and pick the period that matches your return.
   The row for your picked quarter says *matches your return*.
   ![HMRC's obligations: periods 25A4 to 26A4 with due dates and status, 26A3 (1 Jul – 30 Sept 2026) chosen and marked matches your return, and Prepare submission.](img/vat-return-4.png)
   If this goes wrong: nothing matches, so a return filed elsewhere may
   already cover it; check HMRC's list first.
5. Press **Prepare submission**, read the declaration, tick **I confirm the
   information is true and complete**, and submit.
   ![The declaration wording with the confirm box ticked and the Submit (demo — simulated) button outlined.](img/vat-return-5.png)
   If this goes wrong: the button stays disabled, so tick the declaration;
   nothing is sent until you do.
6. Keep the receipt: it is saved to `06 VAT returns/<period key>/` with the
   return, and listed under **Previous receipts**.
   ![Demo — submission simulated, key 26A3: processing date, form bundle number and payment indicator, saved to 06 VAT returns/26A3, and 26A3 under Previous receipts.](img/vat-return-6.png)

## File it yourself: the bridging file

Under **Connect to HMRC**, **File it yourself: VAT bridging file** makes the
picked period's return as a CSV or XLSX file, to download or save in
`07 Reports`. Upload it to HMRC-recognised bridging software (for example
QuickFile, Tax Optimiser, IRIS VAT Filer, 123 Sheets, ANNA or QuickBooks
Online's bridging upload), which sends it to HMRC.

Don't retype or copy and paste the numbers: HMRC's digital-links rule counts a
file exported and uploaded as a digital link, but not copying or retyping.

The file has one sheet and no header row, always laid out the same way, so
you map it once in your bridging software:

| Cells | What |
|---|---|
| A1:A9 | box numbers 1 to 9 |
| **B1:B9** | **the nine values**: B1:B5 pounds and pence, B6:B9 whole pounds (pence dropped) |
| C1:C9 | HMRC's box headings (VAT Notice 700/12) |
| D1:D9 | HMRC's API field names (`vatDueSales` … `totalAcquisitionsExVAT`) |
| A10:B10 | period start (YYYY-MM-DD) |
| A11:B11 | period end |
| A12:B12 | period key (check it against the one your software gets from HMRC) |
| A13:B13 | VAT registration number |
| A14:B14 | whether box 5 is to pay, to reclaim, or nothing |

Box 5 is never negative (HMRC takes it without its sign); row 14 says which
way it goes. A tool that asks for "a column of nine values" takes B1:B9.

QuickBooks Online's bridging upload takes the nine final values as a CSV, but
Intuit doesn't publish the column layout, so there is no QuickBooks-specific
file: map B1 to B9 when QuickBooks asks.

Home's **Deadlines** card and the [Calendar](calendar.md) show the due date,
and **Add to calendar** on the VAT page puts it in your Outlook calendar.

## On Android

**VAT** is a tab of its own: pick the period and read the nine boxes and their
entry counts. Connecting to HMRC and submitting are done on the web.

![Android VAT return for Jul–Sep 2026: the nine boxes with their entry counts, Box 5 net VAT to pay £3,807.33.](img/android-vat.png)
