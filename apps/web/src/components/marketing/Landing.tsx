import Link from "next/link";
import EarlyAccessForm from "@/components/early-access/EarlyAccessForm";
import Prelaunch from "@/components/Prelaunch";
import { GUIDES, GUIDES_URL } from "@/lib/howto-guides";
import { LAUNCH, NOTIFY_HREF, PRELAUNCH_IN_BUILD, SUBMISSION_MODE } from "@/lib/public-site";
import { BrowserFrame, PhoneFrame, Shot } from "./Marks";
import AskLink from "./AskLink";
import DemoLink from "./DemoLink";
import ProcessDemo from "./ProcessDemo";
import ScreenTabs from "./ScreenTabs";

/*
 * The public landing page (signed out on `/`). The words come from docs/marketing/COPY.md (the copy deck,
 * hero option B), checked line by line against the code and docs/HONESTY.md; where a line changed, the reason is in
 * docs/reviews/site-layout/REVIEW.md. Every screen is a real screenshot (sample books). When a claim changes, change
 * it here, in COPY.md and in services/runtime/app/public_kb.md (the chat's notes).
 */

/** Who it is for (WhoFor): only what this build does for each, with what it does not do said plainly. */
const AUDIENCES = [
  {
    title: "Small businesses",
    body: "Receipts, invoices, bank, VAT returns, reports and pay-run estimates for a limited company or a partnership.",
  },
  {
    title: "Sole traders",
    body: "The same books, plus the quarterly Making Tax Digital for Income Tax figures for your self-employment.",
  },
  {
    title: "Landlords",
    body: "Rent, letting-agent statements and property bills in the same approve-first books, with the UK property income figures for each property worked out by code. The HMRC connection is sandbox only.",
  },
  {
    title: "Personal finances",
    body: "Budgets, bills and savings goals from your own bank statements: switch on Show personal finances in Settings.",
  },
];

/** How it works, four steps (COPY.md; step 1 also names voice, which the owner's brief asks for). */
const STEPS = [
  {
    title: "Send it in",
    body: "Photograph a receipt in the Android app, upload it on the web, or let receipts arrive from your email inbox. You can also just say what you need.",
  },
  {
    title: "The AI proposes",
    body: "An AI model reads the document and suggests supplier, category, VAT and totals. Code checks the arithmetic.",
  },
  {
    title: "You approve",
    body: "Each proposal waits in Review. Approve, edit or reject. Nothing posts on its own.",
  },
  {
    title: "VAT and records, ready",
    body: "Approved entries build your ledger, your VAT boxes and a spreadsheet copy of your books.",
  },
];

/** The ten feature blocks of COPY.md, each with its fictional example; Landing places them by theme. */
type Block = { title: string; body: string; example: string };

const BLOCK = {
  receipts: {
    title: "Receipts from email and photos",
    body: "Snap a receipt on your phone or let supplier emails be picked up from your inbox. The AI reads each one into a proposal you check.",
    example:
      "A £60 plus VAT invoice from a fictional supplier, Brightfix Electrical Ltd, arrives by email and waits in Review with supplier, date and totals filled in.",
  },
  bank: {
    title: "Bank lines, matched and coded",
    body: "Import a bank statement as a CSV file and see each line matched to entries already in your books. Confirm the matches and deal with the rest one by one.",
    example: "A fictional £240 payment to Brightfix Electrical Ltd matches the bill for the same amount dated four days earlier.",
  },
  vat: {
    title: "VAT boxes, worked out by code",
    body: "Your nine VAT boxes are calculated by code from approved entries, not typed by hand. Download them as a bridging file to file through your bridging software, or practise the HMRC flow on the sandbox.",
    example: "A fictional quarter for Harthill Bakery Ltd shows £1,240 in Box 1 and £310 in Box 4.",
  },
  itsa: {
    title: "Income Tax for the self-employed",
    body: "If you are self-employed, quarterly Income Tax figures are worked out from your approved entries, with the ledger lines behind each box. The HMRC connection here is sandbox only.",
    example: "A fictional sole trader, Emma Hughes, sees £18,400 of turnover for the period to 5 July with each line traceable.",
  },
  payroll: {
    title: "Pay runs, estimated in pence",
    body: "Enter hours and rates to get a pay-run estimate with tax and National Insurance shown line by line. These are estimates for planning, not payroll filings.",
    example: "A fictional employee, Tom Ellis, on 20 hours at £13.50 an hour gets a gross of £270 with deductions listed beside it.",
  },
  voice: {
    title: "Voice and chat that wait",
    body: "Ask a question in plain words, typed or spoken, and get an answer with figures checked against your books. Short instructions become cards you approve first.",
    example:
      "“Andy did 2 hours on the Hendon job” becomes a timesheet card for the Hendon job, and nothing is recorded until you tap Approve.",
  },
  monthEnd: {
    title: "Month-end checks, listed plainly",
    body: "Run a month-end check that lists missing statements, uncategorised costs, possible duplicates and anything dated into a closed month. Work through the list and re-close when done.",
    example: "Fictional March books for Bramblewood Joinery Ltd flag two unmatched bank lines and one receipt still sitting in the inbox.",
  },
  paypal: {
    title: "PayPal, in the same approve-first books",
    body: "Put a PayPal pay link on your invoices, then Sync PayPal: each sale, purchase and fee is proposed with its journal, you choose the VAT on a sale with no invoice, and the PayPal balance is tied out against your books. Tried with PayPal's sandbox; nothing posts until you approve it.",
    example:
      "A fictional customer pays a £372.00 invoice through its PayPal link; the payment and PayPal's £11.09 fee wait on Invoices until you tap Approve.",
  },
  billpay: {
    title: "Supplier bills paid through PayPal",
    body: "Approve a bill now and it is paid from your PayPal on its due date, only if nothing about it changed. Upcoming payments go in your calendar, a dispute's evidence is built from your books, and one switch stops every automatic payment.",
    example: "A fictional £51.90 bill from Novex Office Supplies Ltd, approved today, is paid on 12 November, the day it falls due.",
  },
  oneDrive: {
    title: "Your books live in OneDrive",
    body: "Your ledger, documents and spreadsheets are files in your own OneDrive folder. Accnomos keeps no database of your books.",
    example:
      "Disconnect and the fictional folder for Bramblewood Joinery Ltd, with its ledger events and Books.xlsx, is still sitting in your OneDrive.",
  },
} satisfies Record<string, Block>;

function BlockText({ block }: { block: Block }) {
  return (
    <>
      <h3 className="font-extrabold">{block.title}</h3>
      <p className="mt-1 text-[15px] leading-relaxed">{block.body}</p>
      <p className="mt-2 text-sm leading-relaxed text-muted">Example: {block.example}</p>
    </>
  );
}

/** COPY.md's ten questions; answers 1 and 10 corrected (REVIEW.md). The last two are pre-launch build only. */
const FAQ: { q: string; a: React.ReactNode }[] = [
  {
    q: "How much does it cost?",
    a: (
      <>
        Every account starts with a 3-month free trial, no card needed. After that, Starter is £10, Comprehensive £20 and Ultimate £50 a month
        ex VAT (2 months free if you pay yearly). The demo with sample books costs nothing to try.{" "}
        <Link href="/pricing" className="font-bold underline underline-offset-2">See the plans</Link>.
      </>
    ),
  },
  {
    q: "Where are my books kept?",
    a: "In your own OneDrive, as files you can open. We keep no database of your books.",
  },
  {
    q: "Does it file to HMRC?",
    a: "The HMRC connection in the product today is sandbox only, for VAT and for self-employed Income Tax. It is there to practise the full flow, not to file a live return. HMRC has closed production access for new Income Tax quarterly-update products for the 2026-27 tax year, so live Income Tax filing from Accnomos cannot start before the 2027-28 year; live VAT filing needs a separate HMRC production application. Filing to HMRC from Accnomos is planned. Until then, File it yourself gives you the VAT return as a bridging file to upload to HMRC-recognised bridging software, the Income Tax quarterly figures for MTD software, and your Self Assessment self-employment pages box by box.",
  },
  {
    q: "Can I use it outside the UK?",
    a: "Yes. Choose your country when you set up: you say whether you charge VAT, GST or sales tax and at what rate, and your books are kept in your own currency. Bookkeeping, Review, invoices, reports and CSV exports work the same; HMRC filing, payroll and Making Tax Digital are UK only and stay hidden.",
  },
  {
    q: "Which banks are covered?",
    a: "You import bank statements as CSV files. Barclays, Starling, Tide and Monzo style layouts are read, along with HSBC and Lloyds style paid-in and paid-out columns.",
  },
  {
    q: "Can I use it on my phone?",
    a: "There is an Android app with capture, Review, Ask, VAT and reports. Everyday admin such as bank uploads and detailed settings stays on the web.",
  },
  {
    q: "Can I switch from Xero or QuickBooks?",
    a: "Export your lists and statements from your current software and bring them across as files. Your opening position is entered once, and new documents flow in from there.",
  },
  {
    q: "How do I start the free trial?",
    a: (
      <>
        Sign in with Microsoft: the 3-month trial starts at once and needs no card.{" "}
        <Link href="/pricing" className="font-bold underline underline-offset-2">See what each plan includes</Link>.
      </>
    ),
  },
  {
    q: "Does my accountant need an account?",
    a: "Only a Microsoft account. In Settings, Your accountant, you invite them by email and choose view only or view and edit: your Accnomos folder in OneDrive is shared with them, and they open your books in the Accountant portal. Remove access there at any time.",
  },
  {
    q: "Can an accountant review my books for me?",
    a: "Where it is offered, you can opt in, in Settings, Your accountant, to have Accnomos accountants, our own accounting team, check your books. It is separate from inviting your own accountant: you read what they can see before you agree, and Stop reviews removes the sharing at once. They never submit anything to HMRC for you and never move money.",
  },
  {
    q: "What can the AI get wrong?",
    a: "It can misread a total, a date or a VAT number, most often on crumpled photos or faint print. That is why every reading is checked by code and waits for your approval before it posts.",
  },
  {
    q: "How do I stop?",
    a: "Export your files first if you wish, then disconnect. Your books are already files in your OneDrive, so nothing is locked in.",
  },
  {
    q: "Is my data used to train models?",
    a: "We do not use your documents to train models: they are read to keep your books, and nothing else. When your server uses an API key, the document goes to that model provider under its own terms.",
  },
  ...(SUBMISSION_MODE
    ? []
    : [
        {
          q: "When can I use it for my own business?",
          a: `The public launch is ${LAUNCH}. You can try the demo with the sample books now.`,
        },
        {
          q: "Is there an iPhone app?",
          a: "Not yet: the iPhone app is coming soon. There is an Android app today, and the web app works in an iPhone's browser.",
        },
      ]),
];

/**
 * Structured data for the public landing page: who publishes it and what the
 * software is. No ratings, no review counts, no offers: none are claimed here.
 */
function StructuredData() {
  const data = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        name: "Accnomos",
        url: "https://accnomos.com",
        logo: "https://accnomos.com/brand/icon-512.png",
      },
      {
        "@type": "SoftwareApplication",
        name: "Accnomos",
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web, Android",
      },
    ],
  };
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}

export default function Landing() {
  return (
    <>
      <StructuredData />
      <Hero />
      <WhoFor />
      <Process />
      <Features />
      <Mtd />
      <AskAndActions />
      <Android />
      <Accountants />
      <YourData />
      <Pricing />
      <Guides />
      <Faq />
      {/* The pre-launch build keeps its own early-list form (never in a submission build); the submission build points to the free trial instead. */}
      {PRELAUNCH_IN_BUILD && (
        <div id="join" className="mx-auto max-w-3xl scroll-mt-20 px-4 pb-16 sm:px-6">
          <Prelaunch>
            <EarlyAccessForm source="/" />
          </Prelaunch>
        </div>
      )}
      <Closing />
    </>
  );
}

/**
 * The calls to action. Submission build: "Try the demo" (the company), "Try the personal demo" (a household's own
 * money) and "Sign in with Microsoft", with "Join the waiting list"
 * (the sign-up near the end of the page) between them in the hero. Pre-launch build: "get notified" by e-mail first,
 * the demo second (sign-in moves to the menu's "Early access / testers").
 */
function CtaPair({ dark = false, join = false }: { dark?: boolean; join?: boolean }) {
  const primary = "rounded-xl bg-brass px-5 py-3 text-base font-extrabold text-ink hover:bg-brass-light";
  const secondary = `rounded-xl border-2 px-5 py-[10px] text-base font-extrabold ${
    dark ? "border-ground/40 text-ground hover:border-ground" : "border-teal-dark text-teal-dark hover:bg-teal-tint"
  }`;
  if (!SUBMISSION_MODE) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <a href={NOTIFY_HREF} className={primary}>
          Launching {LAUNCH} — get notified
        </a>
        <DemoLink className={secondary} />
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <DemoLink className={primary} />
      <DemoLink kind="personal" className={secondary}>
        Try the personal demo
      </DemoLink>
      {join && (
        <Link href="/pricing" className={secondary}>
          Start your free trial
        </Link>
      )}
      <Link href="/connect?next=%2F" className={secondary}>
        Sign in with Microsoft
      </Link>
    </div>
  );
}

/** Which apps exist. Submission build: only what is there; pre-launch build: the iPhone app as coming soon. */
function AppChips({ dark }: { dark: boolean }) {
  const solid = dark ? "bg-white/10 text-ground" : "bg-ink text-ground";
  const quiet = dark ? "border border-white/25 text-ground/80" : "border border-ink/25 text-muted";
  return (
    <ul aria-label="Apps" className="flex flex-wrap gap-2 text-sm font-bold">
      <li className={`rounded-full px-3 py-1 ${solid}`}>Available on Android</li>
      {!SUBMISSION_MODE && <li className={`rounded-full px-3 py-1 ${quiet}`}>iPhone app: coming soon</li>}
      <li className={`rounded-full px-3 py-1 ${quiet}`}>Web, in any browser</li>
    </ul>
  );
}

function Hero() {
  return (
    <section aria-labelledby="hero-title" className="on-dark ledger-rule relative overflow-hidden bg-ledger text-ground">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-16 pt-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:pb-20 lg:pt-14">
        <div>
          <p className="text-[15px] font-semibold text-ground/75">
            Bookkeeping and Making Tax Digital for UK small businesses, sole traders, landlords and personal finances
          </p>
          <h1 id="hero-title" className="hero-lines mt-4 font-extrabold tracking-[-0.035em]">
            Bookkeeping you only have to check
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ground/85">
            The AI reads each document and proposes an entry. Nothing posts until you approve it.
          </p>
          <div className="mt-5">
            <AppChips dark />
          </div>
          <div className="mt-7">
            <CtaPair dark join />
          </div>
          <p className="mt-4 text-sm text-ground/70">
            The demo uses fictional sample books and needs no sign-in. HMRC contact is sandbox only.
          </p>
        </div>

        <div className="hero-devices relative mx-auto w-full max-w-[640px] pl-[28%] sm:pl-[24%] lg:max-w-none">
          <BrowserFrame className="hero-laptop">
            <Shot
              src="/shots/hero-review-1280.webp"
              srcSet="/shots/hero-review-640.webp 640w, /shots/hero-review-1280.webp 1280w"
              sizes="(min-width: 1024px) 600px, 72vw"
              width={1280}
              height={860}
              eager
              priority
              alt="Accnomos Review in the demo sandbox, books of the fictional Bramblewood Joinery Ltd: a timber and hardware invoice from Northgate Timber & Hardware Supplies, £643.80 with £107.30 VAT to reclaim, shown beside its proposed entry and the Approve, Edit and Reject buttons."
            />
          </BrowserFrame>
          <PhoneFrame className="hero-phone absolute -bottom-12 left-0 w-[34%] max-w-[200px] sm:w-[30%]">
            <Shot
              src="/shots/hero-phone.webp"
              srcSet="/shots/hero-phone-200.webp 200w, /shots/hero-phone.webp 390w"
              sizes="(min-width: 640px) 200px, 34vw"
              width={390}
              height={907}
              eager
              alt="The same Northgate invoice on a phone: supplier and amount, the proposed entry (materials £536.50, VAT to reclaim £107.30) and the Approve, Edit and Reject buttons."
            />
          </PhoneFrame>
          {/* The phone frame overhangs the column's left edge: the caption starts clear of it. */}
          <p className="mt-16 pl-[8%] text-right text-[13px] text-ground/65">
            One invoice on the phone and on the web: the real app in its demo sandbox, with the fictional sample books.
          </p>
        </div>
      </div>
    </section>
  );
}

function SectionHead({ id, title, lead }: { id: string; title: string; lead?: React.ReactNode }) {
  return (
    <div className="max-w-2xl">
      <h2 id={id} className="text-3xl font-extrabold leading-tight tracking-[-0.02em] sm:text-4xl">
        {title}
      </h2>
      {lead && <p className="mt-3 text-lg leading-relaxed text-muted">{lead}</p>}
    </div>
  );
}

function WhoFor() {
  return (
    <section id="who" aria-labelledby="who-title" className="scroll-mt-20 border-b border-border bg-white py-14">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <h2 id="who-title" className="text-2xl font-extrabold tracking-[-0.02em] sm:text-3xl">
          One set of books, whoever you are
        </h2>
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {AUDIENCES.map((a) => (
            <li key={a.title} className="border-l-2 border-brass pl-4">
              <h3 className="font-extrabold">{a.title}</h3>
              <p className="mt-1 text-[15px] leading-relaxed text-muted">{a.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Process() {
  return (
    <section id="how" aria-labelledby="how-title" className="scroll-mt-20 py-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <SectionHead
          id="how-title"
          title="How it works"
          lead="Four steps for every document. Below, one receipt goes through them on real screens from the app."
        />
        <ol aria-label="The four steps" className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((st, i) => (
            <li key={st.title} className="rounded-2xl border border-border bg-white p-5">
              <p className="text-sm font-extrabold text-teal-dark">Step {i + 1}</p>
              <h3 className="mt-1 text-lg font-extrabold">{st.title}</h3>
              <p className="mt-1 text-[15px] leading-relaxed text-muted">{st.body}</p>
            </li>
          ))}
        </ol>
        <h3 className="mt-12 text-xl font-extrabold">From a till receipt to Box 4</h3>
        <div className="mt-6">
          <ProcessDemo />
        </div>
        <p className="mt-8 text-[15px]">
          <Link href="/how-it-works" className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
            Read how each feature works, and what is not verified yet
          </Link>
        </p>
      </div>
    </section>
  );
}

function Features() {
  const blocks = [BLOCK.receipts, BLOCK.bank, BLOCK.paypal, BLOCK.billpay, BLOCK.payroll, BLOCK.monthEnd];
  return (
    <section id="features" aria-labelledby="features-title" className="scroll-mt-20 border-t border-border bg-white py-20">
      <div className="mx-auto grid max-w-6xl gap-12 px-4 sm:px-6 lg:grid-cols-2">
        <div>
          <SectionHead
            id="features-title"
            title="The rest of the books, in the same place"
            lead="Receipts, the bank, PayPal, pay runs and month-end, all from the same approved entries."
          />
          <ul className="mt-8 grid gap-x-8 gap-y-7 sm:grid-cols-2">
            {blocks.map((b) => (
              <li key={b.title} className="border-l-2 border-teal pl-4">
                <BlockText block={b} />
              </li>
            ))}
          </ul>
        </div>
        <div className="lg:pt-2">
          <ScreenTabs />
        </div>
      </div>
    </section>
  );
}

function AskAndActions() {
  return (
    <section id="ask" aria-labelledby="ask-title" className="scroll-mt-20 py-20">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 sm:px-6 lg:grid-cols-2">
        <div className="relative pb-24 sm:pb-32">
          <BrowserFrame>
            <Shot
              src="/shots/feat-ask.webp"
              width={808}
              height={560}
              alt="Ask: “How much VAT have I reclaimed this quarter?” answered with net VAT £8.65 for this quarter and £0.00 last quarter, the figures by code and the ledger folder they came from."
            />
          </BrowserFrame>
          <BrowserFrame className="absolute -bottom-2 left-6 right-[-8px] sm:left-16">
            <Shot
              src="/shots/feat-action.webp"
              width={808}
              height={400}
              alt="A proposed invoice card from the request “send a £100 invoice to JM Trading”: £100 plus £20 VAT, £120 due 4 December 2026, with Approve, Change and Reject."
            />
          </BrowserFrame>
        </div>
        <div>
          <SectionHead id="ask-title" title={BLOCK.voice.title} lead={BLOCK.voice.body} />
          <p className="mt-4 text-[15px] leading-relaxed text-muted">Example: {BLOCK.voice.example}</p>
          <p className="mt-4 text-sm text-muted">
            Spoken questions are turned into text by a speech-to-text model; it is used live, and measured on synthetic recordings only.
          </p>
        </div>
      </div>
    </section>
  );
}

function Mtd() {
  return (
    <section id="mtd" aria-labelledby="mtd-title" className="scroll-mt-20 py-20">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 sm:px-6 lg:grid-cols-2">
        <div>
          <SectionHead
            id="mtd-title"
            title="Making Tax Digital, for VAT and Income Tax"
            lead="Figures for HMRC come from code, never from a model."
          />
          <div className="mt-8 grid gap-4">
            {[BLOCK.vat, BLOCK.itsa].map((b) => (
              <div key={b.title} className="rounded-2xl border border-border bg-white p-5">
                <BlockText block={b} />
              </div>
            ))}
          </div>
        </div>
        <BrowserFrame>
          <Shot
            src="/shots/step-5-vat.webp"
            width={808}
            height={560}
            alt="The VAT return page: Box 4, VAT reclaimed on purchases, £8.65 after the Novex receipt was approved."
          />
        </BrowserFrame>
      </div>
    </section>
  );
}

/**
 * Accountants: only what the accountant portal and Settings › Your accountant do (app/accountant.py, the
 * accountant portal). Reviews by Accnomos accountants appear only where the server sets ACCOUNTANT_TEAM_EMAIL.
 */
function Accountants() {
  const card = "rounded-2xl border border-border bg-ground p-5";
  const link = "font-bold text-teal-dark underline underline-offset-2 hover:text-teal";
  return (
    <section id="accountants" aria-labelledby="accountants-title" className="scroll-mt-20 border-y border-border bg-white py-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <SectionHead
          id="accountants-title"
          title="For accountants"
          lead="Have your books reviewed by an accountant: your own, or ours. Either way they open the same files you see: the ledger, Books.xlsx, reports and the audit trail."
        />
        <ul aria-label="Two ways to have your books reviewed" className="mt-8 grid gap-4 md:grid-cols-2">
          <li className={card}>
            <h3 className="font-extrabold">Invite your own accountant</h3>
            <p className="mt-1 text-[15px] leading-relaxed">
              Enter their email and choose view only or view and edit. Your Accnomos folder in OneDrive is shared with
              their Microsoft account, and they open your books in the Accountant portal. Remove access at any time and
              the sharing stops at once.
            </p>
          </li>
          <li className={card}>
            <h3 className="font-extrabold">Or opt in to a review by Accnomos accountants</h3>
            <p className="mt-1 text-[15px] leading-relaxed">
              Where it is offered, you can opt in to have our own accounting team review your books. It is a separate,
              explicit choice: you read what they can see before you agree, and Stop reviews removes the sharing at once.
              They never submit anything to HMRC for you and never move money.
            </p>
          </li>
        </ul>
        <p className="mt-6 max-w-3xl text-[15px] leading-relaxed">
          Both are in{" "}
          <Link href="/settings#settings-accountant" className={link}>
            Settings › Your accountant
          </Link>
          . An accountant can leave a query on a transaction or document, which you answer there; with edit access,
          every change they make is recorded in your audit trail under their name, and anything they question can be
          undone with a reversing entry, never a delete. Accountants open their clients&apos; books in the{" "}
          <Link href="/accountant" className={link}>
            Accountant portal
          </Link>
          .
        </p>
      </div>
    </section>
  );
}

function Pricing() {
  return (
    <section id="pricing" aria-labelledby="pricing-title" className="scroll-mt-20 border-t border-border py-20">
      <div className="mx-auto grid max-w-6xl items-center gap-8 px-4 sm:px-6 md:grid-cols-[minmax(0,1fr)_auto]">
        <SectionHead
          id="pricing-title"
          title="Pricing"
          lead={
            SUBMISSION_MODE
              ? "Start with a 3-month free trial, no card needed. Then Starter is £10, Comprehensive £20 and Ultimate £50 a month ex VAT, with your own AI allowed on every plan. The demo needs no account and no card."
              : "Start with a 3-month free trial, no card needed. The demo needs no account and no card."
          }
        />
        <CtaPair join />
      </div>
    </section>
  );
}

function Android() {
  return (
    <section id="android" aria-labelledby="android-title" className="scroll-mt-20 border-y border-border bg-teal-tint py-20">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 sm:px-6 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
        <div>
          <SectionHead
            id="android-title"
            title="Made for the phone in your pocket"
            lead="Snap a receipt with the camera and it lands in your OneDrive inbox; review it, approve it, ask with the microphone and check the VAT return. The web app shows the same books, because both read the same files."
          />
          <div className="mt-5">
            <AppChips dark={false} />
          </div>
          <ul className="mt-6 space-y-3 text-[15px] leading-relaxed">
            <li>Home, Review, Ask, VAT, and a More tab with files, contacts, invoices, bank, reports and the audit trail.</li>
            <li>Bank CSV upload, reconciling and HMRC filing stay on the web.</li>
            <li className="text-muted">
              Automated tests run on every change. The app has run on one real phone (the owner&rsquo;s) and on the emulator,
              not on other phones yet. A build has been submitted to Google Play and is in Google&rsquo;s review.
            </li>
          </ul>
        </div>
        <figure>
          <div className="flex justify-center gap-4 sm:gap-6">
            <PhoneFrame className="w-[46%] max-w-[210px] translate-y-6">
              <Shot
                src="/shots/android-review.webp"
                width={360}
                height={800}
                alt="Android app, Review 1 of 6: Fictional Plastics Ltd, £126.00, 97 % sure, read by the hosted model, with the net, the VAT to reclaim, the supplier VAT number and Approve, Edit and Reject."
              />
            </PhoneFrame>
            <PhoneFrame className="w-[46%] max-w-[210px]">
              <Shot
                src="/shots/android-ask.webp"
                width={360}
                height={800}
                alt="Android app, Ask: suggested questions such as “Why is Box 5 higher this quarter?”, with the mic, hands-free and a box to type."
              />
            </PhoneFrame>
          </div>
          <figcaption className="mt-10 text-center text-[13px] text-muted">
            The Android app on an emulator, in the company demo with its labelled sample data.
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

function YourData() {
  return (
    <section id="privacy" aria-labelledby="privacy-title" className="scroll-mt-20 py-20">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 sm:px-6 lg:grid-cols-2">
        <div>
          <SectionHead id="privacy-title" title={BLOCK.oneDrive.title} lead={BLOCK.oneDrive.body} />
          <p className="mt-4 text-[15px] leading-relaxed text-muted">Example: {BLOCK.oneDrive.example}</p>
          <h3 className="mt-8 text-xl font-extrabold">AI proposes, you approve</h3>
          <p className="mt-2 text-[15px] leading-relaxed">
            Every figure that reaches your books has passed code checks in whole pence, and a second reading checks the
            first on key documents. There is no database of your books on our side: the files live in your OneDrive.
            Every approve, reject, match, payment and undo is written to an audit trail you can open.
          </p>
          <p className="mt-6 text-[15px]">
            <Link href="/privacy" className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
              Read the privacy policy and data map
            </Link>
          </p>
        </div>
        <BrowserFrame>
          <Shot
            src="/shots/feat-files.webp"
            width={808}
            height={560}
            alt="Files: the Accnomos folder in OneDrive with 00 Inbox, 01 Receipts, 02 Needs a look, 03 Sales, 04 Bank statements, 05 Payroll, 06 VAT returns, 07 Reports, README.txt and _System."
          />
        </BrowserFrame>
      </div>
    </section>
  );
}

/** How-to guides: the featured guides from docs/howto as cards, each with a screenshot from the guide (sample books). */
function Guides() {
  const featured = GUIDES.filter((g) => g.featured);
  const link = "font-bold text-teal-dark underline underline-offset-2 hover:text-teal";
  return (
    <section id="guides" aria-labelledby="guides-title" className="scroll-mt-20 border-t border-border bg-ground py-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <SectionHead
          id="guides-title"
          title="How-to guides"
          lead="Step-by-step guides with a screenshot for every step, taken from fictional sample books, with the Android app where it differs."
        />
        <ul aria-label="How-to guides" className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {featured.map((g) => (
            <li
              key={g.file}
              className="relative flex flex-col overflow-hidden rounded-2xl border border-border bg-white focus-within:ring-2 focus-within:ring-teal hover:border-teal"
            >
              <Shot src={`/howto/${g.file}.webp`} width={640} height={400} alt={g.alt} className="border-b border-border" />
              <div className="flex flex-1 flex-col p-5">
                <h3 className="text-lg font-extrabold">
                  <a
                    href={`${GUIDES_URL}/${g.file}.md`}
                    className="after:absolute after:inset-0 after:content-[''] focus:outline-none"
                  >
                    {g.title}
                  </a>
                </h3>
                <p className="mt-1 text-[15px] leading-relaxed text-muted">{g.summary}</p>
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-[15px]">
          <a href={`${GUIDES_URL}/README.md`} className={link}>
            All {GUIDES.length} guides
          </a>
          <Link href="/how-it-works#guides" className={link}>
            The guides on How it works
          </Link>
        </p>
      </div>
    </section>
  );
}

function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-title" className="scroll-mt-20 border-t border-border bg-white py-20">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 sm:px-6 lg:grid-cols-[minmax(0,4fr)_minmax(0,7fr)]">
        <div>
          <SectionHead id="faq-title" title="Questions" lead="Something else? Ask the chat, which answers from the team's notes." />
          <div className="mt-6">
            <AskLink />
          </div>
        </div>
        <div className="divide-y divide-border border-y border-border">
          {FAQ.map((f) => (
            <details key={f.q} className="faq group">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-[17px] font-extrabold">
                {f.q}
                <span aria-hidden="true" className="faq-icon text-2xl font-normal leading-none text-teal">
                  +
                </span>
              </summary>
              <p className="pb-5 pr-8 text-[15px] leading-relaxed text-muted">{f.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function Closing() {
  return (
    <section aria-labelledby="closing-title" className="on-dark ledger-rule bg-ledger py-16 text-ground">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 sm:px-6 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 id="closing-title" className="text-3xl font-extrabold tracking-[-0.02em]">
            See it with the sample books
          </h2>
          <p className="mt-2 max-w-xl text-ground/80">
            Bramblewood Joinery Ltd is a fictional business. Look through Review, the VAT return, Ask and the reports
            before you connect anything of your own.
          </p>
        </div>
        <CtaPair dark />
      </div>
    </section>
  );
}
