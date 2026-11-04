# Demo video script v2 (4 Nov 2026)

The script is 2:55 long and has 8 spoken scenes plus a silent judges' slide. The owner's master copy is the Claude Doc "Accnomos — demo video script and submission answers", tab "Script v2 (4 Nov)".

| # | Time | On screen (web · Android) | Voice |
|---|---|---|---|
| 1 | 0:00–0:22 | Brown title card, then Home on web and phone side by side | Most accounting apps are built for accountants. They're boring, full of jargon, and they don't teach you anything about your own money. We wanted the opposite: an app that keeps you up to date with your business in plain English, and helps you set goals and actually meet them. |
| 2 | 0:22–0:35 | Goals page: a goal with its AI progress note; spending by category | Once you can see your numbers clearly, you make better decisions. You trim the costs you don't need, set clear goals and watch your progress every week. |
| 3 | 0:35–1:00 | Company demo (Bramblewood Joinery). The Home AI summary as a sorted list; tap an action button. Then the phone: Talk button → "Add a site visit tomorrow at ten" → clash check → "yes" | This is Accnomos, running on Meta's Muse models. Home tells me what needs me now, in order, with a button for each. I can just talk: "add a site visit tomorrow at ten". It checks my calendar for clashes and asks before it changes anything. |
| 4 | 1:00–1:28 | Phone camera → receipt → Review card ("Read by Muse Spark", code checks ticked) → Approve. Web: type "send a £450 invoice to Hartwell" → card → tap Approve | Snap a receipt and Muse Spark reads it. Code checks every number, and I approve. Typing works too: "send a £450 invoice to Hartwell". Anything that moves money needs a tap, never just my voice. The AI proposes, code does the maths, and I decide. |
| 5 | 1:28–1:48 | Reports: profit and loss, CSV export. VAT: nine boxes worked out by code → Submit to HMRC → receipt with the form bundle number | Reports and CSV exports are one click. When the quarter ends, code works out the VAT return from the ledger, and I submit it to HMRC with one tap. |
| 6 | 1:48–2:12 | Switch profile: the sole trader's quarterly income tax update; the landlord's rent and property costs; then the personal demo (the Harrison household): budget, bills in the calendar, a savings goal | It isn't only for companies. Sole traders and landlords get their quarterly Making Tax Digital updates. And at home, the same app runs your household budget, puts your bills in your calendar and keeps your savings goals on track. |
| 7 | 2:12–2:40 | Settings › AI: the three choices and the local-only warning. Then the /ai/calls record showing Glimmer and Muse Spark. Then Settings › Files and backups: your OneDrive folder, Books.xlsx, version history | You choose which Meta model answers first: Muse Spark on the Meta API, or Muse Glimmer, Meta's open-weight model, running on your own computer, so nothing leaves it. Your books live in your own OneDrive, with its backups and version history. We write the code. The data, the drive and the AI are yours. |
| 8 | 2:40–2:55 | Brown end card: accnomos.com · github.com/zaytunazs/accnomos | We hope Accnomos takes the stress out of money, for businesses and for families: less time on paperwork, more time on what matters. One note: in this demo, HMRC filing goes to HMRC's sandbox, because live filing needs HMRC to approve the software first. |
| 9 | 2:55–3:00 | Judges' slide, no voice (below) | — |

## Judges' slide (on screen only)

- **Meta models at run time:**
  - Muse Spark 1.3 (Meta Model API, the default);
  - Muse Glimmer 30B (Meta open weights, on our own GPU server or the user's computer);
  - Muse Voice Transcribe.

  Muse Image made the art at build time.
- **Measured:** share of the 200 synthetic documents with all fields right, clean / messy:

  | Model | Clean | Messy |
  |---|---|---|
  | Muse Spark 1.3 | 95 % | 96 % |
  | Glimmer | 85 % | 80 % |

- **Provenance:** live call records for both models are in `docs/submission/OPEN_WEIGHTS.md`.
- **Try it:** accnomos.com → Try the demo. The Android APK is on GitHub Releases; the Play listing is in review.
- **Limits:** HMRC filing is sandbox only, and the demo data is fictional.
