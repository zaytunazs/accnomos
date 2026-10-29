# Do a VAT return

Who this is for: a VAT-registered owner filing through Making Tax Digital. The
HMRC connection in the product today is sandbox only: it practises the full
flow, not a live filing.

1. Open the VAT return (`/vat`) and pick the quarter.
   ![the quarter picker with the current period and the nine boxes worked out by code.](img/vat-return-1.png)
   If this goes wrong: the boxes show the wrong period, so check the stagger
   in onboarding and Settings first.
2. Check each box against the ledger lines behind it.
   ![one open box with the entries that make up its figure.](img/vat-return-2.png)
   If this goes wrong: a figure looks off, so find the entry in Review or Bank
   and undo it; the boxes rebuild.
3. Press *Connect to HMRC (sandbox)* and sign in with the test user.
   ![the sandbox connect button and the HMRC sign-in, with no production address anywhere.](img/vat-return-3.png)
   If this goes wrong: the redirect fails, so check the relay address allows
   this site before retrying.
4. Open obligations and pick the matching period.
   ![HMRC's obligations list beside your periods, with any date mismatch explained in plain words.](img/vat-return-4.png)
   If this goes wrong: nothing matches, so a return filed elsewhere already
   covers it; check HMRC's list first.
5. Read the declaration, tick it, and submit.
   ![the legal declaration wording with the tick box and the Submit to HMRC (sandbox) button.](img/vat-return-5.png)
   If this goes wrong: the button stays disabled, so scroll back: a box was
   edited after the last check.
6. Keep the receipt saved to `06 VAT returns/<periodKey>/`.
   ![the receipt file in the period folder and the submitted marker on /vat.](img/vat-return-6.png)
   If this goes wrong: the period still shows open, so reload; the receipt
   file is what counts.
