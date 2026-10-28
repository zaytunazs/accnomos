import Link from "next/link";
import EarlyAccessForm from "@/components/early-access/EarlyAccessForm";
import Prelaunch from "@/components/Prelaunch";
import { HONESTY_URL, LAUNCH, NOTIFY_HREF, PRELAUNCH_IN_BUILD, SUBMISSION_MODE } from "@/lib/public-site";
import { BrowserFrame, PhoneFrame, Shot } from "./Marks";
import AskLink from "./AskLink";
import DemoLink from "./DemoLink";
import ProcessDemo from "./ProcessDemo";
import ScreenTabs from "./ScreenTabs";

/*
 * The public landing page (signed out on `/`). Every claim here comes from README.md, docs/HONESTY.md and
 * docs/submission/{DESCRIPTION,JUDGING,META_MODELS}.md, and every screen is a real screenshot (sample books).
 * When a claim changes there, change it here and in services/runtime/app/public_kb.md (the chat's notes).
 */

const PROMISES = [
  { line: "AI proposes.", note: "A Meta model reads each receipt, invoice or credit note." },
  { line: "You approve.", note: "Nothing reaches your books until you tap Approve." },
  { line: "Code calculates.", note: "The ledger and the nine VAT boxes are worked out by code." },
];

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
    body: "Rent, letting-agent statements and property bills in the same approve-first books. Separate property-income (SA105) figures are not in this build.",
  },
  {
    title: "Personal finances",
    body: "Budgets, bills and savings goals from your own bank statements: switch on Show personal finances in Settings.",
  },
];

/** The four steps every document goes through (Process). */
const STEPS = [
  {
    title: "Send it in",
    body: "Forward it to your Outlook, snap it in the Android app, upload it, or just say what you need: “send a £100 invoice to JM Trading”.",
  },
  {
    title: "AI proposes",
    body: "A Meta model reads it and proposes the entry. Code checks the sums, the VAT and whether you have seen it before.",
  },
  {
    title: "You approve",
    body: "Approve, change or reject it on the phone or the web. Nothing reaches your books without you, and Undo is one tap.",
  },
  {
    title: "HMRC-ready",
    body: "Code works out the nine VAT boxes and your Income Tax quarterly figures, ready to submit. Direct submission runs in HMRC's sandbox.",
  },
];

const FEATURES = [
  {
    title: "Receipts straight from your email",
    body: `Switch on Outlook intake and likely bills and receipts in your mailbox are copied to 00 Inbox for review.${
      SUBMISSION_MODE ? "" : " Add more mailboxes: coming soon."
    }`,
  },
  {
    title: "Receipts and review",
    body: "Upload, photograph or drop documents into 00 Inbox. Each one becomes a card to approve, edit or reject, with Undo.",
  },
  {
    title: "VAT return, box by box",
    body: "The nine boxes for any period, with the entries behind each. Submission goes through HMRC's sandbox for now.",
  },
  {
    title: "Invoicing",
    body: "Invoices with a PDF, sent from your own Outlook after you confirm. Part payments, credit notes and refunds.",
  },
  {
    title: "Bank",
    body: "Import a CSV statement, set rules, and match lines to invoices and bills. A match posts nothing until you confirm.",
  },
  {
    title: "Contacts and reports",
    body: "Statements and ageing per customer or supplier; profit and loss, aged balances, VAT by period and a 12-month trend.",
  },
  {
    title: "An audit trail",
    body: "Every action, by you or by an agent, with who did it and a plain sentence. Jobs, mileage and pay-run estimates too.",
  },
];

const MODELS: { name: string; where: string; job: string; status: string; tone: "good" | "plain" | "off" }[] = [
  {
    name: "Muse Glimmer 30B",
    where: "Open weights, on our NVIDIA DGX Spark",
    job: "Reads documents; writes Ask answers, inbox triage and reminders",
    status: "Measured on 400 synthetic documents",
    tone: "good",
  },
  {
    name: "Muse Spark Open",
    where: "Baseten, key mode",
    job: "Independent second reading (the Verifier)",
    status: "Measured on 400 synthetic documents",
    tone: "good",
  },
  {
    name: "Muse Spark 1.3",
    where: "Meta Model API, with your own key",
    job: "The same jobs as Glimmer, without a GPU",
    status: "Unit-tested only, not called live",
    tone: "plain",
  },
  {
    name: "Muse Voice Transcribe",
    where: "Meta Model API, key mode",
    job: "Spoken questions on Ask and Android",
    status: "Unit-tested only, no live microphone run",
    tone: "plain",
  },
  {
    name: "SAM 3.1",
    where: "Meta Model API, key mode",
    job: "Crops a messy receipt photo before reading",
    status: "Off by default; a code crop is used",
    tone: "off",
  },
  {
    name: "Muse Image",
    where: "Build time only",
    job: "Made the brand art; not in the running product",
    status: "Run once, 12 images",
    tone: "plain",
  },
];

const FAQ: { q: string; a: React.ReactNode }[] = [
  {
    q: "Can I file my real VAT return with it today?",
    a: "Not yet. Accnomos is built for Making Tax Digital, but submitting to HMRC goes to HMRC's sandbox (its test service, with test data) and has been tested against a stand-in for HMRC, not yet run end to end against the sandbox itself. The nine VAT boxes are worked out by code from the entries you approved.",
  },
  {
    q: "Where are my books kept?",
    a: "In your own Microsoft OneDrive, in an Accnomos folder: 00 Inbox to 07 Reports, Books.xlsx for your accountant, and a _System folder with the ledger. Accnomos runs no user database and keeps no copy. Disconnect and every file is still yours.",
  },
  {
    q: "Does the AI post anything without me?",
    a: "Not by default. Every proposal waits for your Approve. Autopilot is an opt-in level that may post purchases from suppliers you have a rule for, and each post can be undone. Accnomos never sends email from your inbox on its own.",
  },
  {
    q: "Can it pick up receipts from my email?",
    a: `Yes, from Outlook: switch on Outlook intake and likely bills and receipts are copied to 00 Inbox, where they wait for your Approve like any other document. It has been tested on fictional emails, not yet on a real mailbox.${
      SUBMISSION_MODE ? "" : " Adding more mailboxes is coming soon."
    }`,
  },
  {
    q: "Which AI reads my receipts?",
    a: "Muse Glimmer 30B, Meta's open-weight model, on our DGX Spark; or Muse Spark 1.3 through the Meta Model API with your own key. “On our machine” means the server running Accnomos, not your laptop.",
  },
  {
    q: "How accurate is it?",
    a: "On 200 clean and 200 messy synthetic documents, every field was right on 85 % and 80 % of documents for Glimmer and 91 % and 93 % for Muse Spark Open. Real phone photos will score lower, which is why every reading waits on a card for you to check.",
  },
  {
    q: "What does it cost?",
    a: "There is no published pricing. Accnomos is a hackathon build, and the sample books are free to try here without an account.",
  },
  {
    q: "Do I need a Microsoft account?",
    a: "For your own books, yes: they live in your OneDrive, and you sign in with a personal or work Microsoft account. To look around first, open the sample books; no sign-in needed.",
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

export default function Landing() {
  return (
    <>
      <Hero />
      <WhoFor />
      <Process />
      <Features />
      <Mtd />
      <AskAndActions />
      <Android />
      <Accountants />
      <YourData />
      <Models />
      <Status />
      <Pricing />
      <Faq />
      {/* The early-adopter sign-up: pre-launch build only (in neither the HTML nor the payload of a submission build). */}
      {PRELAUNCH_IN_BUILD && (
        <Prelaunch>
          <div className="mx-auto max-w-3xl px-4 pb-16 sm:px-6">
            <EarlyAccessForm source="/" />
          </div>
        </Prelaunch>
      )}
      <Closing />
    </>
  );
}

/**
 * The two calls to action. Submission build: "Try the demo" and "Sign in with Microsoft". Pre-launch build: "get
 * notified" by e-mail first, the demo second (sign-in moves to the menu's "Early access / testers").
 */
function CtaPair({ dark = false }: { dark?: boolean }) {
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
          <div className="hero-promises mt-4">
            <h1 id="hero-title" className="hero-lines font-extrabold tracking-[-0.035em]">
              {PROMISES.map((p) => (
                <span key={p.line} className="block">
                  {p.line}
                </span>
              ))}
            </h1>
            <ul aria-label="What that means" className="hero-notes">
              {PROMISES.map((p) => (
                <li key={p.line}>{p.note}</li>
              ))}
            </ul>
          </div>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ground/85">
            Forward a receipt, snap a photo or just say what you need. Accnomos proposes the entry, you approve it,
            and your VAT and Income Tax figures are ready for HMRC, with the books kept in your own OneDrive.
          </p>
          <div className="mt-4">
            <AppChips dark />
          </div>
          <div className="mt-7">
            <CtaPair dark />
          </div>
          <p className="mt-4 text-sm text-ground/70">
            The demo uses fictional sample books and needs no sign-in. Submitting to HMRC uses HMRC&apos;s sandbox.
          </p>
        </div>

        <div className="hero-devices relative mx-auto w-full max-w-[640px] pl-[28%] sm:pl-[24%] lg:max-w-none">
          <BrowserFrame className="hero-laptop">
            <Shot
              src="/shots/hero-review-1280.webp"
              srcSet="/shots/hero-review-640.webp 640w, /shots/hero-review-1280.webp 1280w"
              sizes="(min-width: 1024px) 600px, 72vw"
              width={1280}
              height={800}
              eager
              priority
              alt="Accnomos Review page: the Novex Office Supplies receipt has been read, £51.90 with £8.65 VAT, confidence 97 %, waiting for approval."
            />
          </BrowserFrame>
          <PhoneFrame className="hero-phone absolute -bottom-12 left-0 w-[34%] max-w-[200px] sm:w-[30%]">
            <Shot
              src="/shots/hero-phone.webp"
              srcSet="/shots/hero-phone-200.webp 200w, /shots/hero-phone.webp 390w"
              sizes="(min-width: 640px) 200px, 34vw"
              width={390}
              height={844}
              eager
              alt="The same Novex proposal on a phone, with the proposed entry: office supplies £43.25, VAT to reclaim £8.65."
            />
          </PhoneFrame>
          <p className="mt-16 text-right text-[13px] text-ground/65">
            One receipt on the phone and on the web: the real app, with the fictional sample books.
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
  return (
    <section id="features" aria-labelledby="features-title" className="scroll-mt-20 border-t border-border bg-white py-20">
      <div className="mx-auto grid max-w-6xl gap-12 px-4 sm:px-6 lg:grid-cols-2">
        <div>
          <SectionHead
            id="features-title"
            title="The rest of the books, in the same place"
            lead="Around the receipts sits what a VAT-registered small business keeps every month."
          />
          <dl className="mt-8 grid gap-x-8 gap-y-6 sm:grid-cols-2">
            {FEATURES.map((f) => (
              <div key={f.title} className="border-l-2 border-teal pl-4">
                <dt className="font-extrabold">{f.title}</dt>
                <dd className="mt-1 text-[15px] leading-relaxed text-muted">{f.body}</dd>
              </div>
            ))}
          </dl>
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
          <SectionHead
            id="ask-title"
            title="Ask by voice or chat, then approve what it suggests"
            lead="Type or say a question in plain English. The figures are calculated by code from your ledger; the AI only writes the words."
          />
          <ul className="mt-6 space-y-3 text-[15px] leading-relaxed">
            <li>Every figure in an answer is checked against your books, and each answer shows the files it used.</li>
            <li>
              Ask for an action, like sending an invoice: code finds the customer and prices the lines, and a card
              waits for your Approve.
            </li>
            <li className="text-muted">
              Voice questions use Muse Voice Transcribe in key mode; that path is unit-tested only.
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}

function Mtd() {
  const cards = [
    {
      title: "MTD for VAT",
      points: [
        "The nine boxes for any period, worked out by code from the entries you approved, with the entries behind each box.",
        "Check the obligations, prepare the return and confirm the declaration, all in one page.",
      ],
      status:
        "Submission goes to HMRC's sandbox. It is tested against a stand-in for HMRC, not yet end to end against the sandbox itself.",
    },
    {
      title: "MTD for Income Tax",
      points: [
        "Quarterly updates for self-employment, worked out by code from the same approved entries: income and expenses by HMRC category.",
        "Switch it on in Settings with “I am self-employed”.",
      ],
      status:
        "Sandbox only. Built and tested against HMRC's published example payloads; it has never been run against HMRC.",
    },
  ];
  return (
    <section id="mtd" aria-labelledby="mtd-title" className="scroll-mt-20 py-20">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 sm:px-6 lg:grid-cols-2">
        <div>
          <SectionHead
            id="mtd-title"
            title="Making Tax Digital, for VAT and Income Tax"
            lead="Numbers for HMRC come from code, never from a model. Accnomos prepares them; you check and send."
          />
          <div className="mt-8 grid gap-4">
            {cards.map((c) => (
              <div key={c.title} className="rounded-2xl border border-border bg-white p-5">
                <h3 className="text-lg font-extrabold">{c.title}</h3>
                <ul className="mt-2 list-disc space-y-1.5 pl-5 text-[15px] leading-relaxed">
                  {c.points.map((pt) => (
                    <li key={pt}>{pt}</li>
                  ))}
                </ul>
                <p className="mt-3 text-sm text-muted">{c.status}</p>
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

function Accountants() {
  return (
    <section id="accountants" aria-labelledby="accountants-title" className="scroll-mt-20 py-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <SectionHead
          id="accountants-title"
          title="For accountants"
          lead="Your client keeps the books; you get clean, checkable records without logging in to yet another system."
        />
        <ul className="mt-8 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
          <li className="border-l-2 border-teal pl-4">
            <h3 className="font-extrabold">Books.xlsx</h3>
            <p className="mt-1 text-[15px] leading-relaxed text-muted">
              Rebuilt in your client&apos;s Accnomos folder after every change: the ledger, VAT and reports in one workbook.
            </p>
          </li>
          <li className="border-l-2 border-teal pl-4">
            <h3 className="font-extrabold">Exports</h3>
            <p className="mt-1 text-[15px] leading-relaxed text-muted">
              Everything as one zip of CSVs, ready for your own software.
            </p>
          </li>
          <li className="border-l-2 border-teal pl-4">
            <h3 className="font-extrabold">An audit trail</h3>
            <p className="mt-1 text-[15px] leading-relaxed text-muted">
              Every entry with who approved it, which document it came from, and a plain sentence.
            </p>
          </li>
          <li className="border-l-2 border-teal pl-4">
            <h3 className="font-extrabold">Shared from OneDrive</h3>
            <p className="mt-1 text-[15px] leading-relaxed text-muted">
              Your client shares their Accnomos folder with you in OneDrive. A portal for accountants is not in this build.
            </p>
          </li>
        </ul>
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
              ? "No charge. There is no published pricing: Accnomos is a hackathon build. The demo needs no account and no card; your own books need only a Microsoft account."
              : "Free while we launch. The demo needs no account and no card; your own books need only a Microsoft account."
          }
        />
        <CtaPair />
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
              248 automated tests run on every change, but nothing has been tried on a real phone yet. A build has been
              submitted to Google Play.
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
                alt="Android app, Review: a Screwfix receipt, £38.47, matching an Autopilot rule, with the VAT to reclaim and the reason."
              />
            </PhoneFrame>
            <PhoneFrame className="w-[46%] max-w-[210px]">
              <Shot
                src="/shots/android-ask.webp"
                width={360}
                height={800}
                alt="Android app, Ask: a sample answer to “Why is my VAT higher than last quarter?” with the figures and the files used."
              />
            </PhoneFrame>
          </div>
          <figcaption className="mt-10 text-center text-[13px] text-muted">
            The Android app on an emulator, signed out, showing its labelled sample data.
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
          <SectionHead
            id="privacy-title"
            title="Your books stay in your OneDrive"
            lead="The books are files in a folder you own. Accnomos does the work on each request and keeps nothing."
          />
          <ul className="mt-6 space-y-3 text-[15px] leading-relaxed">
            <li>
              <strong>No database of ours.</strong> The ledger is append-only event files in your OneDrive, and
              Books.xlsx is rebuilt for your accountant.
            </li>
            <li>
              <strong>Permissions when you need them.</strong> Mail, contacts and calendar are asked for only the first
              time you use the feature that needs them.
            </li>
            <li>
              <strong>Leave any time.</strong> Export everything as one zip with CSVs; delete the folder and nothing is
              left with us.
            </li>
            <li>
              <strong>Hardened, not load-tested.</strong> Logs are scrubbed of credentials, requests are capped and
              rate-limited, and the service has not been load-tested.
            </li>
          </ul>
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

function Models() {
  const tone = {
    good: "bg-teal-tint text-teal-dark",
    plain: "bg-ground text-muted",
    off: "bg-warn-bg text-warn-ink",
  };
  return (
    <section id="models" aria-labelledby="models-title" className="on-dark scroll-mt-20 bg-ledger py-20 text-ground">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="max-w-2xl">
          <h2 id="models-title" className="text-3xl font-extrabold leading-tight tracking-[-0.02em] sm:text-4xl">
            Six Meta models, each with its status
          </h2>
          <p className="mt-3 text-lg leading-relaxed text-ground/80">
            Models read and write words. Money is always code. Here is where each one runs and how far it has been
            tested.
          </p>
        </div>
        <div className="mt-10 overflow-x-auto rounded-2xl bg-white text-ink" tabIndex={0} aria-label="Meta models table">
          <table className="w-full min-w-[640px] text-left text-[15px]">
            <thead className="border-b border-border text-sm text-muted">
              <tr>
                <th scope="col" className="px-5 py-3 font-bold">Model</th>
                <th scope="col" className="px-5 py-3 font-bold">Runs on</th>
                <th scope="col" className="px-5 py-3 font-bold">What it does here</th>
                <th scope="col" className="px-5 py-3 font-bold">Status</th>
              </tr>
            </thead>
            <tbody>
              {MODELS.map((m) => (
                <tr key={m.name} className="border-b border-border last:border-0">
                  <th scope="row" className="px-5 py-4 font-extrabold">{m.name}</th>
                  <td className="px-5 py-4 text-muted">{m.where}</td>
                  <td className="px-5 py-4">{m.job}</td>
                  <td className="px-5 py-4">
                    <span className={`inline-block rounded-full px-3 py-1 text-[13px] font-bold ${tone[m.tone]}`}>
                      {m.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-sm text-ground/70">
          Accuracy, all on synthetic documents: every field right on 85 % (clean) and 80 % (messy) of 200 documents
          each for Glimmer, and 91 % and 93 % for Spark Open.
        </p>
      </div>
    </section>
  );
}

function Status() {
  const cols = [
    {
      title: "Ran for real",
      items: [
        "Microsoft sign-in and creating the folder",
        "A receipt read by Glimmer on our Spark, approved, posted to the ledger and counted in the VAT boxes",
        "The model evaluations reported above",
      ],
      foot: "On the maintainers' own accounts; no log is committed.",
    },
    {
      title: "Tested on fakes",
      items: [
        "Everything else: invoicing, bank, contacts, reports, Ask, actions, Autopilot",
        "About 1,260 runtime tests, 208 browser tests and 248 Android tests",
        "In-memory OneDrive and mailbox, stubbed models, mocked HMRC",
      ],
      foot: "This proves our logic, not Microsoft, Meta or HMRC.",
    },
    {
      title: "Not in this build",
      items: [
        "Production HMRC filing (sandbox only)",
        "Google Drive, RTI payroll, flat-rate VAT",
        ...(SUBMISSION_MODE ? [] : ["An iPhone app"]),
      ],
      foot: "The full list of gaps is kept in docs/HONESTY.md in the public repository.",
    },
  ];
  return (
    <section id="status" aria-labelledby="status-title" className="scroll-mt-20 py-20">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <SectionHead
          id="status-title"
          title="What is tested, and what is not"
          lead="A hackathon build, described as it is. Demo data is synthetic."
        />
        <div className="mt-10 grid gap-px overflow-hidden rounded-2xl border border-border bg-border md:grid-cols-3">
          {cols.map((c) => (
            <div key={c.title} className="bg-white p-6">
              <h3 className="text-lg font-extrabold">{c.title}</h3>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-relaxed">
                {c.items.map((i) => (
                  <li key={i}>{i}</li>
                ))}
              </ul>
              <p className="mt-4 text-sm text-muted">{c.foot}</p>
            </div>
          ))}
        </div>
        <p className="mt-6 text-[15px]">
          <a href={HONESTY_URL} className="font-bold text-teal-dark underline underline-offset-2 hover:text-teal">
            Read the full list in docs/HONESTY.md
          </a>
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
