# Accnomos: what the public chat may say

This file is the only knowledge the "Ask about Accnomos" chat on the public website is given (`app/public_chat.py`).
Each `## Title {#id}` heading is one section; code picks the sections that match a question and passes only those to
the model. Every statement here comes from `README.md`, `docs/HONESTY.md`, `docs/submission/DESCRIPTION.md`,
`docs/submission/JUDGING.md`, `docs/submission/META_MODELS.md` and the privacy page. Keep it that way: when a claim
changes there, change it here. Keywords after "Keywords:" help retrieval and are not shown to visitors.
Lines starting `[prelaunch] ` are used only on the pre-launch site (PUBLIC_SUBMISSION_MODE=0) and lines starting
`[submission] ` only on the judged build (the default), which never mentions a launch date or "coming soon".

## What Accnomos is {#what-it-is}

Accnomos is bookkeeping and Making Tax Digital (MTD) VAT software for UK small businesses and sole traders who are
VAT-registered and do their own books. Its rule is: AI proposes, you approve, code calculates. A Meta AI model reads
your receipts, invoices and credit notes and proposes an entry; nothing is posted until you tap Approve; the ledger and
the nine VAT boxes are worked out by deterministic code, never by a model. Your books are files in your own Microsoft
OneDrive, and Accnomos keeps no database of its own. It was built by Zaytuna Business Services Ltd (UK) for the Meta
Global AI Developer Hackathon in October 2026, and it is a hackathon build, not a finished commercial product.
Keywords: about, overview, product, purpose, company, built, made, maker, behind, hackathon, bookkeeping, accounting, software, app, sole trader, small business, self-employed, limited company, suitable, landlord, freelancer, contractor

## Receipts, review and the ledger {#receipts-review}

You add a receipt by taking a photo in the Android app, uploading it on the web, dropping it into the 00 Inbox folder
in your OneDrive, or letting Outlook intake copy likely bills and receipts from your mailbox (switched on in
Settings; tested on fictional emails, not yet on a real mailbox). The phone and the web app work on the same files,
so a receipt snapped on the phone waits on Review on the web too.
[prelaunch] Adding more mailboxes is coming soon. Press Scan and the AI
reads the document into structured fields: supplier, date, VAT number, net, VAT and total, lines and how it was paid.
Code then checks the arithmetic and repairs common reading mistakes, an independent second reading (the Verifier) can
check the first, and a review card shows the proposed entry with the reason in plain English. You approve, edit or
reject it. Approving writes a balanced, append-only ledger event to your OneDrive and updates Books.xlsx, a spreadsheet
for your accountant. Corrections are new reversing entries, and there is an undo. PDFs and phone HEIC photos are
accepted; a multi-page PDF is read from page 1 only.
Keywords: receipt, receipts, scan, photo, upload, email, emails, mail, outlook, mailbox, mailboxes, intake, sync, invoice, bill, expense, review, approve, approval, card, ledger, entry, post, books, xlsx, spreadsheet, accountant, verifier, inbox, undo, pdf, heic

## VAT return and HMRC {#vat-hmrc}

The VAT return page shows the nine boxes for a period, calculated by code from your approved entries, with the entries
behind each box. Submitting to HMRC goes through a relay that holds only the HMRC application secret; you sign in on
HMRC's own site, the tokens stay in your browser tab, and a legal declaration tick is required before anything is
sent. Today everything HMRC is sandbox only, meaning HMRC's test service with test data: there is no production HMRC
filing yet, and the full browser flow has not been run end to end against the sandbox. Flat-rate and annual accounting
schemes are not supported. A UK VAT number check (sandbox) and Companies House look-up are built but not used live.
Keywords: vat, return, mtd, making tax digital, hmrc, submit, file, filing, boxes, nine, 9, box, sandbox, quarter, period, deadline, obligations, flat rate, tax

## Invoicing, bank, contacts and reports {#money-features}

Around the receipts sit the rest of a small business's books. Invoicing: create invoices with a PDF, send them from
your own Outlook after you confirm the email, record part payments and overpayments, issue credit notes, and apply or
refund credits. Bank: import a CSV statement (Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts are modelled but
not checked against real exports), set rules, and reconcile lines against invoices and bills. Contacts: customers and
suppliers with statements, ageing and possible-duplicate suggestions that only merge when you tap. Reports: profit and
loss, aged debtors and creditors, VAT by period and a 12-month trend, saved as a spreadsheet. There is also an audit
trail of every action, jobs and timesheets, vehicles and mileage, and payroll estimates (estimates only, not RTI
payroll: no submissions to HMRC for payroll).
Keywords: invoice, invoicing, send, outlook, email, payment, part payment, credit note, refund, bank, statement, csv, import, reconcile, reconciliation, rules, contacts, customers, suppliers, duplicates, reports, profit, loss, aged, debtors, creditors, trend, audit, jobs, timesheets, mileage, vehicles, payroll

## Ask, chat and voice {#ask-chat-voice}

Signed in, the Ask page answers questions about your own books in plain English, such as how much VAT you owe and why.
The numbers are calculated by code from your ledger and the AI only writes the words; every figure in an answer is
checked against the code's facts, and a figure that is not in your books is replaced. Each answer shows the files it
used. You can also ask for actions, for example "send a £100 invoice to JM Trading": the AI only returns the intent,
code finds the customer and prices the lines, and a card waits for you to tap Approve before anything happens. Voice
questions use Muse Voice Transcribe, with Whisper on our own DGX Spark as the fallback, and each answer says which one
heard you; the voice path is unit-tested only and has not been run with a real microphone. Accnomos does not read answers aloud. This public chat is different: it only answers questions about
Accnomos itself and never sees anyone's books.
Keywords: ask, question, questions, chat, chatbot, assistant, voice, speak, microphone, mic, actions, natural language, answer, grounded, figures

## Android app {#android}

There is an Android app (Flutter) with sign-in, receipt capture with the camera, Review, Ask with the microphone and
action cards, Home, the VAT return and a More menu with Files, Contacts (including adding from the phone's contacts),
Invoices, Jobs, Vehicles, Bank, Payroll, Reports and the audit trail. Some tasks, such as bank CSV upload, reconcile
and HMRC filing, stay on the web. The app has 248 automated tests, but nothing on the phone has been run on a real
device yet and a real-phone sign-in is not recorded. A build has been submitted to the Google Play production track
for review. The web app works in an iPhone's browser.
[submission] There is no iPhone app.
[prelaunch] An iPhone app is coming soon.
Keywords: android, phone, mobile, app, play store, google play, camera, iphone, ios, apple, tablet

## Your data stays in your OneDrive {#your-data}

Your books live in your own Microsoft OneDrive, in an Accnomos folder (Apps/Accnomos on personal accounts, /Accnomos
on work accounts), with folders from 00 Inbox to 07 Reports, Books.xlsx and a _System folder holding the ledger
events. Accnomos runs no user database and keeps no copy: the runtime is stateless, works on your OneDrive with the
token each request carries, and discards everything. The app asks for each Microsoft permission only when you first use
the feature that needs it. To leave, disconnect; your files stay in your OneDrive. To delete everything, delete the
Accnomos folder and remove Accnomos from your Microsoft account's apps. Settings, Your data exports everything as one
zip with CSVs. Server access logs (IP address, path, time) are kept for up to 30 days for security. No data is sold,
and there are no advertising or analytics SDKs. Google Drive and Dropbox are not supported.
Keywords: data, privacy, private, onedrive, microsoft, storage, stored, store, where, keep, database, delete, export, leave, cancel, gdpr, permissions, security, secure, safe, google drive, dropbox, cloud, logs

## When you can use it {#availability}

[submission] You can use it now: try the demo with the fictional sample books without signing in, or sign in with a
[submission] Microsoft account to keep your own books in your OneDrive. Submitting VAT returns goes to HMRC's sandbox.
[prelaunch] The public launch is November 2026, when the app will be fully ready; you can try the demo with the
[prelaunch] fictional sample books now, without signing in. To hear when it launches, email the team at the contact
[prelaunch] address shown under the chat.
Keywords: when, launch, launched, release, released, available, availability, ready, use it, start using, open, date, notify, waitlist, wait list

## Signing in and getting started {#getting-started}

You can look around without an account: "Try the sample books" opens the app with a fictional company's books
(Bramblewood Joinery Ltd, labelled SAMPLE). To use your own books, sign in with a Microsoft account (personal or work)
and the connect steps create your Accnomos folder in OneDrive, let you choose your AI and enter your business name, VAT
number and VAT period. An empty folder can be filled with the sample books to try things out; you can delete them by
deleting the folder. You need a Microsoft account with OneDrive; there is no other sign-in option.
Keywords: sign in, login, log in, account, register, sign up, start, getting started, setup, set up, try, demo, sample, microsoft account, onboarding, connect

## The Meta AI models {#meta-models}

Six Meta models are wired in. Muse Glimmer 30B (open weights) runs on Ollama on the team's own NVIDIA DGX Spark and
reads documents and writes Ask answers; it is the model with measured results. Muse Spark 1.3 does the same jobs
through the Meta Model API with your own key; it is unit-tested only and has not been called live. Muse Spark Open on
Baseten is the independent Verifier in key mode and has been measured. Muse Voice Transcribe turns spoken questions
into text (unit-tested only). SAM 3.1 can crop a messy receipt photo but is off by default and has never run live; a
plain-code crop is used instead. Muse Image made the brand art at build time and is not in the running product. "Local"
means the machine running the Accnomos runtime (for the demo, the team's DGX Spark), not your own laptop.
Keywords: ai, model, models, meta, llama, muse, glimmer, spark, open weights, baseten, sam, voice, transcribe, image, gpu, dgx, ollama, local, key, api key, which ai

## How accurate it is {#accuracy}

All figures are on synthetic documents, so real phone photos will score lower. On 200 clean and 200 messy synthetic
documents, every field was read right on 85 % and 80 % of documents by Glimmer 30B and on 91 % and 93 % by Muse Spark
Open, with code repairs, one re-read and the Verifier on. Glimmer takes about 18 seconds per document (24 seconds for
messy ones). Ask quoted figures exactly in 32 of 32 measured answers, and no invented figure reached the user. Because
every proposal waits for your approval, a wrong reading is something you see on the card before it reaches your books.
Keywords: accurate, accuracy, mistakes, errors, wrong, reliable, reliability, trust, measured, eval, evaluation, results, percent, speed, fast, slow, how long, seconds

## Autopilot {#autopilot}

Autopilot is off by default. When you turn it on (level L2), it may post a purchase without your tap, but only for a
supplier you have a rule for, and every Autopilot post can be undone. In a test on 467 synthetic documents with the
Verifier on there were no false posts on 154 clean documents, but 17 false posts overall (3.6 %), all of them re-dated
copies of receipts already posted. Accnomos never sends emails from your inbox on its own; inbox triage only drafts.
Keywords: autopilot, automatic, automation, auto, without approval, rules, hands-free, automatically

## What is tested and what is not {#status}

Honest status: only Microsoft sign-in, folder setup, reading a receipt through approval to the ledger and the VAT
boxes, and the model evaluations have run for real, on the maintainers' own accounts and with no committed log.
Everything else is tested with automated tests against fakes (in-memory OneDrive, mailbox and calendar, stubbed
models and mocked HMRC); that proves the logic, not Microsoft, Meta or HMRC. The test suites cover about 1,260 runtime
tests, 208 browser tests and 248 Android tests. HMRC is sandbox only. Not built yet: production HMRC filing, Google
Drive, RTI payroll and a flat-rate VAT scheme. The full list of known gaps is in the project's docs/HONESTY.md.
Keywords: status, tested, tests, testing, ready, production, live, beta, finished, limitations, limits, gaps, missing, not built, roadmap, honest, honesty, real, works, working, stable

## Pricing and availability {#pricing}

There is no published pricing. Accnomos is a hackathon build: the sample books are free to try on the website, and no
paid plan, price or subscription has been announced. For questions about using it for your business, contact the team.
To get 3 months free, leave your email in the "Get 3 months free" form on the home page or at accnomos.com/join, and
the team will email you to set it up.
Keywords: price, pricing, cost, costs, free, pay, paid, plan, plans, subscription, buy, purchase, how much, trial, licence, license, available, availability, 3 months free, three months free, offer, join, sign up, signup

## Your accountant {#accountant}

In Settings, Your accountant, you can invite your own accountant by email, view only or view and edit: your Accnomos
folder in OneDrive is shared with their Microsoft account and they open your books in the Accountant portal, which
lists the clients who shared books with them. Removing access stops the sharing. Separately, where the server offers
it, you can opt in to reviews by Accnomos accountants, the accounting team of the people who run Accnomos: you read
what they can see before agreeing, and Stop reviews removes the sharing at once. They never submit anything to HMRC
for you and never move money. Accountants can leave queries on a transaction or document, which you answer in
Settings; with edit access, every change they make is recorded in your audit trail under their name.
Keywords: accountant, accountants, bookkeeper, review, reviews, reviewed, check my books, invite, share, sharing, portal, panel, queries, query

## Security {#security}

The runtime and the HMRC relay are stateless and store nothing about you. Requests are hardened: credentials are
scrubbed from logs, request sizes are capped, there is a per-address rate limit, cross-origin access is limited to the
app's exact address, and the containers are hardened. HMRC tokens stay in your browser tab and the relay holds only the
application secret. Ledger files are append-only but are not tamper-evident (no signatures or hash chain). The service
has not been load-tested.
Keywords: security, secure, hacking, encryption, tokens, passwords, password, relay, audit, penetration, safe, protect, attack

## Contacting the team {#contact}

Accnomos is made by Zaytuna Business Services Ltd in the United Kingdom. For anything this chat cannot answer, such as
a specific business situation, partnership, accessibility needs or support, email the team at the contact address
shown under the chat. This chat cannot give tax, legal or accounting advice for your own situation.
Keywords: contact, email, support, help, team, talk, human, person, company, zaytuna, advice, partnership, accessibility
