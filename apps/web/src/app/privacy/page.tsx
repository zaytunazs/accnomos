import { BUILD_PAYMENTS_PROVIDER, PROVIDER_NAME, STRIPE_VISIBLE } from "@/lib/payments";

export const metadata = { title: "Privacy policy — Accnomos" };

/** Who takes payment for plans in this build (lib/payments.ts): named only when one does. */
const PAYMENTS = PROVIDER_NAME[BUILD_PAYMENTS_PROVIDER];

const UPDATED = "11 November 2026";

export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-10 text-ink">
      <h1 className="text-3xl font-extrabold tracking-tight">Privacy policy</h1>
      <p className="mt-2 text-sm text-muted">Accnomos · Zaytuna Business Services Ltd · last updated {UPDATED}</p>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">The short version</h2>
        <p>
          Accnomos keeps your books in <strong>your own Microsoft OneDrive</strong>, or in{" "}
          <strong>your own Google Drive</strong> if you sign in with Google. We keep a small{" "}
          <a className="font-semibold text-teal underline" href="#account-registry">account registry</a> (who you are, your plan and how much you
          have used it) but we do not store your receipts, invoices, ledger, bank lines or VAT figures on our servers. Unless you choose otherwise, the AI that
          reads your documents runs <strong>on our own server</strong>. Only if it cannot answer does the document go to
          our backup AI provider, <strong>Anthropic</strong> (in the United States), under its commercial terms, which
          do not allow it to train models on your content. Since 11 November 2026 our server sends no documents to
          the hosted model&apos;s provider. You can instead run the AI on a machine you control or use your own API key
          (see <a className="font-semibold text-teal underline" href="#ai-documents">where your documents go</a>).
          {/* The "Join the waiting list" list (components/sign-up/JoinForm.tsx; the pre-launch build's EarlyAccessForm). */}
          {" "}The one exception is the{" "}
          <a className="font-semibold text-teal underline" href="#sign-up">waiting list</a>, which holds only what
          you type into it if you choose to sign up.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">What the app accesses</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li><strong>Microsoft account (sign-in):</strong> your name and e-mail, used only to show who is signed in.</li>
          <li><strong>OneDrive app folder:</strong> the app reads and writes files inside its own <em>Accnomos</em> folder (inbox, ledger events, Books.xlsx, VAT returns). It does not read the rest of your drive.</li>
          <li><strong>Sending invoices (Outlook, optional):</strong> the first time you send an invoice or a payment reminder, the app asks Microsoft for permission to send mail as you (<code>Mail.Send</code>). It sends only the email you saw and confirmed, to the address you confirmed, with the invoice PDF attached; a copy is in your Sent Items and the PDF in your <em>Accnomos</em> folder. Reminder wording is drafted by your own AI connection from the invoice number, amount and dates; your bank details are not sent to the AI.</li>
          <li><strong>Google account (sign-in, if you choose Google):</strong> your name and e-mail, used only to show who is signed in. Your books go in an <em>Accnomos</em> folder in your Google Drive (My Drive), and the app can see only the files it created there, never the rest of your Drive.</li>
          <li><strong>Gmail, Google Calendar and Google Contacts (Google sign-in):</strong> Google asks for these at sign-in, all at once (see the table below). Gmail is read to find bills and receipts and the people who email you; Accnomos writes a draft or sends an email only when you have seen it and confirmed it. Calendar events are read to plan your day, and Accnomos writes only the events you approve. Contacts are read so you can tick which to add to your books; nothing is written back.</li>
          <li><strong>Camera / photos (Android):</strong> only when you choose to capture or pick a receipt; the image is uploaded to your books inbox (OneDrive or Google Drive).</li>
          <li><strong>Your AI connection (optional):</strong> by default none: our server&apos;s own AI chain is used (see below). If you choose it, either the address of a model running on your own hardware, or an API key for the hosted model that you paste in. The key is stored on your device and sent only to our stateless runtime over HTTPS to make the request on your behalf; it is never logged or stored server-side.</li>
          <li><strong>HMRC (sandbox; filing to HMRC from Accnomos is planned):</strong> if you connect HMRC, the OAuth tokens stay in your browser session. Our relay holds only the HMRC application secret and forwards requests; it stores nothing about you. HMRC requires fraud-prevention headers (device, screen size, time zone, IP address) which the relay forwards with each request.</li>
        </ul>
      </section>

      <section id="ai-documents" className="mt-8 scroll-mt-6 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Where your documents go for AI reading</h2>
        <p>
          The AI reads a document, or a question you ask, only when you ask it to. Where that request is processed
          depends on your AI choice in Settings.
        </p>
        <ul className="list-disc space-y-2 pl-5">
          <li><strong>Default (you have made no AI choice):</strong> the AI on <strong>our own server</strong> reads it. We do not keep the request.</li>
          <li><strong>Backup, only when our server cannot answer:</strong> if our own server is down, too busy or cannot give a usable reading, the same document or question is sent to <strong>Anthropic</strong> (Anthropic PBC, United States) through its API, under Anthropic&apos;s <a className="font-semibold text-teal underline" href="https://www.anthropic.com/legal/commercial-terms">Commercial Terms</a>, which say it may not train models on the content it receives, and its Data Processing Addendum. Anthropic deletes API inputs and outputs within 30 days unless it must keep them longer to enforce its usage policy or by law (<a className="font-semibold text-teal underline" href="https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data">Anthropic&apos;s retention note</a>); we do not have a zero-retention arrangement with it.</li>
          <li><strong>The hosted model&apos;s provider:</strong> since 11 November 2026 our server sends no documents, questions or recordings to the hosted model&apos;s provider. Before that date our live server used the hosted model&apos;s API in a mode in which the provider may use the content to improve its models; the demo used only fictional sample data.</li>
          <li><strong>Local mode (your choice):</strong> the document goes to the model address you give, on hardware you control, and to nobody else. Spoken questions are transcribed on our own server.</li>
          <li><strong>Your own key (your choice):</strong> the document goes to the hosted model&apos;s API under your key, in standard mode, subject to that provider&apos;s terms for your key. It does not use the server owner&apos;s key.</li>
          <li><strong>Optional extra provider:</strong> a hosted inference provider may be added to the server&apos;s chain as an optional extra provider; it is not used today and this page will be updated if that changes.</li>
        </ul>
        <p>Spoken questions are converted to text on our own server and the audio is not kept.</p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Permissions: what is asked and when</h2>
        <p>
          With a Microsoft account, the app asks for each permission only when you first use the feature that needs it,
          never all at once.
        </p>
        <div role="region" aria-label="Permission table" tabIndex={0} className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-[14px]">
            <thead>
              <tr className="border-b border-border text-[13px] font-bold text-muted">
                <th scope="col" className="py-2 pr-3">Permission</th>
                <th scope="col" className="py-2 pr-3">Asked</th>
                <th scope="col" className="py-2">Used for</th>
              </tr>
            </thead>
            <tbody>
              {[
                { scope: "User.Read, offline_access", when: "At sign-in", use: "Show who is signed in; keep you signed in" },
                { scope: "Files.ReadWrite.AppFolder", when: "At sign-in (personal accounts)", use: "Read and write only the Apps/Accnomos folder: 00 Inbox to 07 Reports, Books.xlsx, _System" },
                { scope: "Files.ReadWrite", when: "At sign-in (work accounts only)", use: "Read and write only the /Accnomos folder; the app folder is personal-accounts only" },
                { scope: "Mail.Read", when: "When you switch on Outlook intake or inbox triage, or open Import contacts › People who email you", use: "Intake copies likely bills to 00 Inbox; triage reads sender, subject, date and a short preview; Import contacts lists who emailed you (names and addresses only)" },
                { scope: "Mail.ReadWrite", when: "The first time you tap Draft in Outlook", use: "Save that one reply as a draft; nothing is ever sent" },
                { scope: "Mail.Send", when: "The first time you send an invoice or reminder, in the confirmation dialog", use: "Send only the email you saw and confirmed, with the invoice PDF" },
                { scope: "Contacts.Read", when: "The first time you open Import contacts › Outlook contacts", use: "List your Outlook contacts so you can tick which to add; ones already in your books only gain a missing email or phone" },
                { scope: "Calendars.Read", when: "The first time you plan a day or open Calendar", use: "Read your default calendar for those days, to plan around it or list it" },
                { scope: "Calendars.ReadWrite", when: "The first time you apply a plan, add or remove an event, or tap Add to calendar on your deadlines", use: "Create the plan’s items, the events you add, and your deadlines as all-day events with a reminder; each event Accnomos writes carries a hidden Accnomos tag, so it only ever updates or removes its own" },
              ].map((row) => (
                <tr key={row.scope} className="border-t border-border align-top first:border-t-0">
                  <td className="py-2 pr-3 font-semibold"><code>{row.scope}</code></td>
                  <td className="py-2 pr-3">{row.when}</td>
                  <td className="py-2">{row.use}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Google permissions (if you sign in with Google)</h2>
        <p>
          Unlike Microsoft, the Google sign-in asks for every permission below at once, on Google&apos;s own consent
          screen; you can untick the optional ones there. The books need only the Google Drive one. You can remove
          Accnomos&apos;s access at any time at{" "}
          <a className="font-semibold text-teal underline" href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>.
        </p>
        <div role="region" aria-label="Google permission table" tabIndex={0} className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-[14px]">
            <thead>
              <tr className="border-b border-border text-[13px] font-bold text-muted">
                <th scope="col" className="py-2 pr-3">Permission</th>
                <th scope="col" className="py-2">Used for</th>
              </tr>
            </thead>
            <tbody>
              {[
                { scope: "openid, email, profile", use: "Show who is signed in" },
                { scope: "drive.file", use: "Create and use the Accnomos folder in My Drive: only files Accnomos made (or you opened with it), never the rest of your Drive" },
                { scope: "gmail.readonly", use: "Read your mail to copy likely bills and receipts to 00 Inbox, sort your inbox and list who emails you; nothing is moved, deleted or marked read" },
                { scope: "gmail.compose", use: "Save a reply as a draft, or send an invoice or reminder you saw and confirmed; never sent on a schedule" },
                { scope: "calendar.events", use: "Read your events to plan a day, and add or change only the events you approve (your deadlines, the plan's items)" },
                { scope: "contacts.readonly", use: "List your Google contacts so you can tick which to add to your books" },
              ].map((row) => (
                <tr key={row.scope} className="border-t border-border align-top first:border-t-0">
                  <td className="py-2 pr-3 font-semibold"><code>{row.scope}</code></td>
                  <td className="py-2">{row.use}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Accnomos&apos;s use and transfer of information received from Google APIs adheres to the{" "}
          <a className="font-semibold text-teal underline" href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>,
          including the Limited Use requirements. Data from Gmail, Drive, Calendar and Contacts is used only to provide the
          features above to you; it is not sold, not used for advertising, not read by people (unless you ask us for
          help with a specific item, or the law requires it) and not used to train AI models. The AI reading described
          above sees a document from Gmail or Drive only when you ask it to read one.
        </p>
      </section>

      <section id="account-registry" className="mt-8 scroll-mt-6 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Your account, plan and billing</h2>
        <p>
          To run plans and billing we keep an account registry in a <strong>Supabase</strong> database in a UK or EU region. It holds account
          details only: your email address, how you signed in (Microsoft or Google) and a stable id from that sign-in, your plan, billing status and
          trial dates, any promo codes you redeemed, monthly usage counts (documents read, questions asked, invoices created) and notes our
          support team adds when helping you. It never holds your books, documents, receipts, bank lines, financial records, or tokens for other services.
        </p>
        {PAYMENTS && (
          <p>
            <strong>Payments for your Accnomos plan are taken by {PAYMENTS}</strong>
            {BUILD_PAYMENTS_PROVIDER === "paypal"
              ? ` (PayPal Subscriptions: you approve the subscription at PayPal, and PayPal takes each payment). PayPal holds your payment method and payment history; we never see your card or your PayPal login. PayPal tells us whether the subscription is active and when a payment is made or fails, and we keep a copy of that status in the registry. PayPal's own privacy statement covers what PayPal does with your details.`
              : ` (checkout, billing and the customer portal). ${PAYMENTS} holds your card and payment history; we never see or store a card number. ${PAYMENTS} tells us your plan and payment status, and we keep a copy of that status in the registry.`}
          </p>
        )}
        <p>
          <strong>Problem reports.</strong> If you use Report a problem, we keep your message, the page you were on, the app version, your browser or
          phone type and a screenshot only if you choose to attach one, until the report is closed and for 12 months after.
        </p>
      </section>

      <section id="analytics" className="mt-8 scroll-mt-6 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Usage analytics and error reports</h2>
        <p>
          <strong>First-party analytics.</strong> The app records which pages and features are used, with counts and durations, against your account
          id, so we can see what works. It goes to our own registry through our own server: no third-party tracker, no cookies, no fingerprinting, and
          never amounts, supplier names, document text, emails or file names. Events are kept for 13 months.{" "}
          <strong>You can turn it off</strong> in Settings → Privacy (&ldquo;Do not collect usage analytics&rdquo;) and nothing more is recorded.
        </p>
        <p>
          <strong>Error reports (Sentry, when enabled).</strong> When switched on, errors in the web app, our server and the Android app are sent to
          Sentry, in its EU data region, with personal data turned off and amounts, emails, VAT numbers and tokens removed before sending. Where it is
          not switched on, nothing is sent.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">What we keep</h2>
        <p>
          Nothing from your books, only the account registry above. The runtime and relay are stateless: requests are processed in memory and discarded. Standard web-server access logs (IP address, path, time) are kept for up to 30 days for security.
          {" "}If you join the waiting list, we keep what you typed into that form, as described next.
        </p>
      </section>

      <section id="sign-up" className="mt-8 scroll-mt-6 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">The waiting list</h2>
        <p>
          You can leave your email on our website to join the Accnomos waiting list. Signing up is optional
          and has nothing to do with using the app.
        </p>
        <ul className="list-disc space-y-2 pl-5">
          <li><strong>Who:</strong> Zaytuna Business Services Ltd, United Kingdom, is the controller of the list. Contact{" "}
            <a className="font-semibold text-teal underline" href="mailto:zohaibsharif@gmail.com">zohaibsharif@gmail.com</a>.</li>
          <li><strong>What we collect:</strong> your email address; your name and how you heard about us, if you give them; what the books would be for (limited company, sole trader, personal, or accountant/bookkeeper); that you ticked the consent box and its exact wording; the page you signed up on; and the date and time. We do not store your IP address with it.</li>
          <li><strong>Why:</strong> to email you when your place on the waiting list comes up, and to know how many people of each kind have signed up. Nothing else: no newsletter, no other products, and we never sell or share the list.</li>
          <li><strong>Lawful basis:</strong> your consent (UK GDPR Article 6(1)(a)), given by ticking the box, which is never pre-ticked. Our email also follows the Privacy and Electronic Communications Regulations.</li>
          <li><strong>Where it is kept:</strong> in one file on a server we run ourselves, readable only by the service operator. Nobody else receives it. If we use an email-sending service to email you, we will name it here first; it would act only on our instructions.</li>
          <li><strong>How long:</strong> we delete the list by the end of November 2027, except for people who have become customers. Unsubscribing deletes your entry straight away.</li>
          <li><strong>Unsubscribe or erase:</strong> reply to our email, or email{" "}
            <a className="font-semibold text-teal underline" href="mailto:zohaibsharif@gmail.com">zohaibsharif@gmail.com</a>{" "}
            from the address you signed up with. Withdrawing consent is as easy as giving it, and we will delete your entry and confirm. You can also ask for a copy of what we hold, or for it to be corrected.</li>
          <li><strong>Complaints:</strong> if you are unhappy with how we handle your data, tell us first. You also have the right to complain to the Information Commissioner&apos;s Office:{" "}
            <a className="font-semibold text-teal underline" href="https://ico.org.uk/make-a-complaint/">ico.org.uk/make-a-complaint</a>, 0303 123 1113.</li>
        </ul>
        <p>No decisions are made about you automatically, and you do not have to sign up to use Accnomos.</p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Data map</h2>
        {/* Focusable and named, so a keyboard user can scroll it sideways on a phone. */}
        <div role="region" aria-label="Data map table" tabIndex={0} className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-[14px]">
            <thead>
              <tr className="border-b border-border text-[13px] font-bold text-muted">
                <th scope="col" className="py-2 pr-3">Data</th>
                <th scope="col" className="py-2 pr-3">Where it lives</th>
                <th scope="col" className="py-2">Who can see it</th>
              </tr>
            </thead>
            <tbody>
              {[
                { data: "00 Inbox, 01 Receipts, 02 Needs a look, 03 Sales (with invoices/ and invoices/sent/), 04 Bank statements, 05 Payroll, 06 VAT returns, 07 Reports, Books.xlsx, README.txt", where: "Your OneDrive Accnomos folder (Apps/Accnomos; /Accnomos on work accounts)", who: "You — plus anyone you share that OneDrive with" },
                { data: "The books: _System/Ledger/events, proposals, docs, audit trail, Autopilot rules", where: "Your OneDrive Accnomos folder, _System/", who: "You — append-only; corrections are new reversing entries" },
                { data: "Working data: Contacts, Jobs, Staff, Timesheets, Vehicles, Mileage, bank, Intake, Todos, Planner, Payroll runs, Invoicing profile", where: "Your OneDrive Accnomos folder, _System/", who: "You — names and details only; money is recomputed from the events" },
                { data: "Microsoft sign-in (name, e-mail)", where: "This browser's sign-in cache", who: "You, shown as who is signed in" },
                { data: "Google sign-in (name, e-mail, a one-hour access token)", where: "This browser's localStorage", who: "You, shown as who is signed in" },
                { data: "Documents and questions sent to the AI (default: no AI choice made)", where: "Read by the AI on our own server; only if it cannot answer, sent over HTTPS to Anthropic's API (United States); not stored by us", who: "Nobody when our server answers; Anthropic as our processor when it is the backup (not used to train its models; deleted within 30 days unless its usage policy or the law needs longer)" },
                { data: "Your API key for the hosted model and AI address", where: "This device only", who: "Sent per request over HTTPS so the runtime can call the model for you; never logged or stored" },
                { data: "HMRC tokens", where: "This browser tab only", who: "Gone when the tab closes or you disconnect" },
                { data: "Device ID and VAT number", where: "This device only", who: "Sent to HMRC as fraud-prevention data when you submit" },
                { data: "Spoken questions", where: "Nowhere — converted then discarded", who: "Nobody keeps the audio" },
                { data: "Questions typed into Ask about Accnomos (the website chat)", where: "Nowhere — answered by our own model from the team's notes, then discarded; not logged", who: "Nobody; it never sees anyone's books" },
                { data: "Mail read during intake and triage", where: "Memory only; copies land in 00 Inbox and to-dos in _System/Todos", who: "You — full bodies and attachments are never fetched by triage" },
                { data: "Calendar days read for planning", where: "Memory only; applied plans in _System/Planner/applied.json", who: "You — nothing written before you tap Apply" },
                { data: "Account registry: email, sign-in kind, plan, billing status, trial dates, promo redemptions, monthly usage counts, support notes", where: "Supabase database (UK or EU region)", who: "The service operator; never your books or financial records" },
                ...(PAYMENTS ? [{ data: "Payment details and payments for your plan", where: PAYMENTS, who: `You and ${PAYMENTS}; we receive only your plan and payment status` }] : []),
                { data: "Usage analytics events (page, feature, counts; off if you opt out)", where: "Our registry, kept 13 months", who: "The service operator" },
                { data: "Problem reports (message, page, app version, browser, optional screenshot)", where: "Our registry", who: "The service operator, until closed plus 12 months" },
                { data: "Error reports (amounts, emails, VAT numbers and tokens removed; only when enabled)", where: "Sentry, EU region", who: "The service operator" },
                { data: "Server access logs (IP, path, time, up to 30 days)", where: "Our hosts", who: "The service operator, for security" },
              ].map((row) => (
                <tr key={row.data} className="border-t border-border align-top first:border-t-0">
                  <td className="py-2 pr-3 font-semibold">{row.data}</td>
                  <td className="py-2 pr-3">{row.where}</td>
                  <td className="py-2">{row.who}</td>
                </tr>
              ))}
              <tr className="border-t border-border align-top">
                <td className="py-2 pr-3 font-semibold">waiting list (only if you sign up): email, optional name, business type, how you heard, consent, time</td>
                <td className="py-2 pr-3">One file on our server (the runtime’s data volume)</td>
                <td className="py-2">The service operator, to email you when your place on the waiting list comes up; deleted by the end of November 2027</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Third parties</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li>Supabase — hosts our account registry (plan, billing status, usage counts, analytics events, problem reports) in a UK or EU region; never your books or financial records.</li>
          {PAYMENTS && <li>{PAYMENTS} — our payment processor for Accnomos plans; it takes the payments and holds your payment method; we receive your plan and payment status.</li>}
          <li>Sentry (EU region) — receives scrubbed error reports, only where error reporting is enabled.</li>
          <li>Microsoft (sign-in and OneDrive) — under your Microsoft account terms.</li>
          <li>Google (sign-in, Google Drive, and Gmail, Calendar and Contacts) — only if you sign in with Google, under your Google account terms.</li>
          <li>Our own server — runs the AI that reads your documents and questions and transcribes spoken questions; nothing is kept.</li>
          <li>Anthropic (Anthropic PBC, United States) — our backup AI provider and a processor: it receives a document or question only when our own server cannot answer, under its Commercial Terms (no training on your content) and Data Processing Addendum. Not used in local mode or with your own key.</li>
          <li>The hosted model&apos;s provider — only with your own API key, if you provide one, under that provider&apos;s terms for your key. Our server sends it nothing of yours.</li>
          <li>Our web host (IONOS, the server that terminates HTTPS for accnomos.com and api.accnomos.com) — carries your requests, including document content, over an encrypted tunnel to our own server; it is a processor for that transport only.</li>
          <li>TrueLayer — only if you connect a bank for bank feeds; it receives your bank sign-in choice and consent, and returns account and transaction data, which we write to your OneDrive.</li>
          <li>{STRIPE_VISIBLE ? "PayPal and Stripe — only if you connect either" : "PayPal — only if you connect it"} for payment links on invoices; {STRIPE_VISIBLE ? "they receive" : "it receives"} the invoice amount, reference and description needed to create the link, and {STRIPE_VISIBLE ? "tell" : "tells"} us when it is paid.</li>
          <li>A hosted inference provider chosen by the server owner — only if you use your own key and the server owner has switched on a hosted second-reading model; the document image is then sent there for an independent second reading. It is off today. In local mode documents are never sent there.</li>
          <li>HM Revenue &amp; Customs — only if you connect HMRC.</li>
        </ul>
        <p>
          We do not sell data, we use no advertising, and we have no third-party analytics scripts or cookies.
          {" "}The waiting list is not shared with anyone.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Your data: export and leaving</h2>
        <p>
          <strong>Export.</strong> Settings → Your data → <em>Export your data</em> saves everything as one zip in{" "}
          <em>07 Reports/Exports</em> in your OneDrive (<em>accnomos-export-&lt;date&gt;.zip</em>): ledger events,
          proposals, contacts, invoices with an index of the invoice PDFs, payments, bank lines, rules, the audit
          trail and the saved VAT returns — plus a README explaining each file and one CSV per main table
          (ledger lines, contacts, invoices, payments) so it opens in Excel. A second export the same day is kept
          beside the first, never overwritten.
        </p>
        <p>
          <strong>Where things live.</strong> Your books live in your OneDrive, in the Accnomos app folder. This
          browser keeps your sign-in, AI choice and settings in its own localStorage (HMRC tokens live only in the
          tab). The runtime keeps nothing: it works on your OneDrive with the token each request carries and
          discards everything. There is no copy of your books on our side: only the account registry above.
        </p>
        <p>
          <strong>Leaving.</strong> Disconnect clears this browser&apos;s sign-in and settings; your files stay in
          your OneDrive. To delete the books, delete the Accnomos folder in your OneDrive and remove Accnomos at{" "}
          <a className="font-semibold text-teal underline" href="https://account.live.com/myapps">account.live.com/myapps</a>{" "}
          (signed in with Google: delete the Accnomos folder in your Google Drive and remove Accnomos at{" "}
          <a className="font-semibold text-teal underline" href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>).
          No server-side delete of your books is needed, because nothing from them is stored server-side; to delete your account registry entry, email us
          {" "}(the <a className="font-semibold text-teal underline" href="#sign-up">waiting list</a> is separate)
          .
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Deleting your data</h2>
        <p>
          Delete the <em>Accnomos</em> folder in your OneDrive (or Google Drive) and sign out of the app. Because we hold no copy, that removes all of your books.
          To delete your account registry entry as well (plan, usage counts, reports), email us from your sign-in address; cancel any paid plan first
          in Settings → Plan &amp; billing.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Contact</h2>
        <p>
          Zaytuna Business Services Ltd, United Kingdom · <a className="font-semibold text-teal underline" href="mailto:zohaibsharif@gmail.com">zohaibsharif@gmail.com</a>
        </p>
      </section>
    </div>
  );
}
