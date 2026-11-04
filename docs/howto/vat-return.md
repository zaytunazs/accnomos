# Do a VAT return

Who this is for: a VAT-registered owner filing through Making Tax Digital.
The HMRC connection here is sandbox only: it practises the full flow, not a
live filing. In the demo, HMRC is not contacted at all and the receipt is made
up so you can see every step.

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
3. Under **Connect to HMRC**, press **Connect to HMRC (sandbox)** (in the demo,
   **Connect to HMRC (simulated)**) and sign in with HMRC's test user.
   ![Connect to HMRC in the demo: the note that HMRC is not contacted, what signing in involves, and the Connect to HMRC (simulated) button.](img/vat-return-3.png)
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

Home's **Deadlines** card and the [Calendar](calendar.md) show the due date,
and **Add to calendar** on the VAT page puts it in your Outlook calendar.

## On Android

**VAT** is a tab of its own: pick the period and read the nine boxes and their
entry counts. Connecting to HMRC and submitting are done on the web.

![Android VAT return for Jul–Sep 2026: the nine boxes with their entry counts, Box 5 net VAT to pay £3,807.33.](img/android-vat.png)
