# Teaser posts

Ready-to-paste text for the teaser videos in this folder. Built by `python tools/teaser/build.py`.

| File | Use |
|---|---|
| `accnomos-teaser1-16x9_social.mp4` | X, Facebook feed, YouTube (public launch messaging: "Launching November 2026") |
| `accnomos-teaser1-1x1_social.mp4` | X and Facebook feed, square |
| `accnomos-teaser1-16x9_submission.mp4` | Hackathon submission and judges: no launch date, no "coming soon" beats, end card "accnomos.com · Try the demo" |
| `accnomos-teaser1-1x1_submission.mp4` | The same, square |
| `accnomos-teaser1-thumbnail.png` | YouTube thumbnail, 1280×720 |

Rules kept in every text below (from `docs/HONESTY.md`): HMRC is sandbox only, so we say "MTD-ready", never "files to HMRC";
the screens show fictional sample books; the AI reads and code calculates; nothing posts without the owner's approval.
The social cut's "Compare what you pay" and "iPhone app" beats are marked coming soon in the video itself; the
submission cut leaves them out. Use the X, Facebook and YouTube texts below with the social cut.
The hackathon has no official hashtag in our docs, so the posts use topic hashtags only. Add the official one if Meta announces one.

## X (≤ 280 characters)

> Bookkeeping that does itself. Meta Muse models read your receipts, code checks the sums, you approve. VAT worked out by code; books stay in your own OneDrive. Built for the Meta Global AI Developer Hackathon. Launching November 2026 · accnomos.com #MakingTaxDigital #AI

(280 characters as X counts them, the link as 23.)

## Facebook

> Bookkeeping that does itself.
>
> Accnomos is bookkeeping and Making Tax Digital VAT for UK small businesses, built in one week for the Meta Global AI Developer Hackathon.
>
> - Snap a receipt on your phone, or let it pull receipts and invoices from your Outlook inbox.
> - Meta Muse models read the paperwork. Code checks the arithmetic.
> - Nothing reaches your books until you tap Approve.
> - Your 9-box VAT return is worked out by code from the entries you approved (MTD-ready; HMRC connection tested in HMRC's sandbox).
> - Ask your books anything and get real figures with the files they came from. Voice commands are built in too, and every action waits for your OK.
> - Your books stay in your own OneDrive. We keep no database.
>
> Android app and web app today; iPhone app coming soon.
>
> Launching November 2026 · accnomos.com
>
> (The video shows a fictional sample company.)

## YouTube

**Title** (≤ 100 characters):

> Accnomos: bookkeeping that does itself (UK VAT, Meta Muse models) | Meta AI Hackathon

**Description:**

> Bookkeeping that does itself. Snap a receipt; Meta Muse models read it, code checks the sums, and nothing reaches your books until you approve.
>
> Accnomos is bookkeeping and Making Tax Digital VAT for UK small businesses, built in one week for the Meta Global AI Developer Hackathon (indie track).
>
> In this video:
> - Snap a receipt on your phone; it appears on the web, ready to approve
> - Receipts and invoices pulled from your Outlook email
> - Ask for a report in plain English and get exact figures
> - Hands-free voice commands
> - Plan your day around your jobs
> - VAT returns built for Making Tax Digital (HMRC sandbox today)
> - Your books stay in your own OneDrive
>
> AI by Meta Muse models (Muse Glimmer 30B on our own hardware, with Muse Spark Open as an independent second reader). The VAT boxes are calculated by code, never by the model. HMRC submission is tested against HMRC's sandbox only.
>
> All screens are from the app with a fictional sample company. Music is original, synthesised in code for this video. Voice: Kokoro TTS (Apache-2.0).
>
> Launching November 2026 · https://accnomos.com

For the submission upload (`*_submission.mp4`) replace the last line with "Try the demo · https://accnomos.com". (No chapter timestamps: YouTube needs chapters of at least 10 seconds, and the beats here are 2–4 s.)

**Tags:**

> Accnomos, bookkeeping, UK VAT, Making Tax Digital, MTD, VAT return, small business, sole trader, receipts, receipt scanner, AI bookkeeping, AI accounting, Meta Muse, Meta AI, Meta Global AI Developer Hackathon, OneDrive, Outlook, Android app

## Credits

- Voice: Kokoro TTS (Apache-2.0), voice bm_george. Captions in the video are the spoken words.
- Music: original, synthesised in code (`tools/teaser/music.py`); no samples.
- Illustration and app icon: made with Meta Muse Image (`tools/brand_muse.py`).
- Screens: the Accnomos web and Android apps with fictional sample data.

## Alt text (video)

> A 44-second animated teaser for Accnomos with upbeat electronic music, a British male voice-over and matching captions. It opens on "Bookkeeping that does itself" and "Snap a receipt. Done." beside an illustration of a phone scanning a crumpled receipt into a ledger. Screens from the Android and web apps follow, all showing fictional sample data: a Screwfix receipt read on the phone; a review card on the web; the approved state; the OneDrive folder where emailed receipts land; an Ask answer explaining why VAT rose; a 12-month sales and purchases chart; a spoken question on the phone; a "Compare what you pay — coming soon" card; the Home page with a "Plan today" button; a nine-box VAT return with £2,140 to pay, labelled HMRC sandbox; the OneDrive files list; and two Android phones. It ends on a teal card with the Accnomos logo, "accnomos.com" and "Launching November 2026".

Submission cut: no "Compare what you pay" card and no iPhone line; the voice says "And plan your day around your jobs" instead of the compare line; the last phones card reads "On Android and the web"; the end card says "accnomos.com" and "Try the demo", with no launch line.
