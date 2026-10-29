import Prelaunch from "@/components/Prelaunch";
import { PRELAUNCH_IN_BUILD } from "@/lib/public-site";

export const metadata = { title: "Privacy policy — Accnomos" };

const UPDATED = "28 October 2026";

export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-10 text-ink">
      <h1 className="text-3xl font-extrabold tracking-tight">Privacy policy</h1>
      <p className="mt-2 text-sm text-muted">Accnomos · Zaytuna Business Services Ltd · last updated {UPDATED}</p>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">The short version</h2>
        <p>
          Accnomos keeps your books in <strong>your own Microsoft OneDrive</strong>. We do not run a user database and we
          do not store your receipts, invoices, ledger or VAT figures on our servers. The AI that reads your documents runs
          either on a machine you control or through an API key you provide.
          {/* The early-adopter list exists only in the pre-launch build (EarlyAccessForm.tsx). */}
          {PRELAUNCH_IN_BUILD && (
            <Prelaunch>
              {" "}The one exception is the{" "}
              <a className="font-semibold text-teal underline" href="#early-access">early-adopter list</a>, which holds
              only what you type into it if you choose to join.
            </Prelaunch>
          )}
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">What the app accesses</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li><strong>Microsoft account (sign-in):</strong> your name and e-mail, used only to show who is signed in.</li>
          <li><strong>OneDrive app folder:</strong> the app reads and writes files inside its own <em>Accnomos</em> folder (inbox, ledger events, Books.xlsx, VAT returns). It does not read the rest of your drive.</li>
          <li><strong>Sending invoices (Outlook, optional):</strong> the first time you send an invoice or a payment reminder, the app asks Microsoft for permission to send mail as you (<code>Mail.Send</code>). It sends only the email you saw and confirmed, to the address you confirmed, with the invoice PDF attached; a copy is in your Sent Items and the PDF in your <em>Accnomos</em> folder. Reminder wording is drafted by your own AI connection from the invoice number, amount and dates; your bank details are not sent to the AI.</li>
          <li><strong>Camera / photos (Android):</strong> only when you choose to capture or pick a receipt; the image is uploaded to your OneDrive inbox.</li>
          <li><strong>Your AI connection:</strong> either the address of a model running on your own hardware (e.g. Muse Glimmer), or a Meta Model API key you paste in. The key is stored on your device and sent only to our stateless runtime over HTTPS to make the request on your behalf; it is never logged or stored server-side.</li>
          <li><strong>HMRC (sandbox during the hackathon):</strong> if you connect HMRC, the OAuth tokens stay in your browser session. Our relay holds only the HMRC application secret and forwards requests; it stores nothing about you. HMRC requires fraud-prevention headers (device, screen size, time zone, IP address) which the relay forwards with each request.</li>
        </ul>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Permissions: what is asked and when</h2>
        <p>
          The app asks for each permission only when you first use the feature that needs it, never all at once.
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
                { scope: "Mail.Read", when: "When you switch on Outlook intake or inbox triage", use: "Intake copies likely bills to 00 Inbox; triage reads sender, subject, date and a short preview" },
                { scope: "Mail.ReadWrite", when: "The first time you tap Draft in Outlook", use: "Save that one reply as a draft; nothing is ever sent" },
                { scope: "Mail.Send", when: "The first time you send an invoice or reminder, in the confirmation dialog", use: "Send only the email you saw and confirmed, with the invoice PDF" },
                { scope: "Contacts.Read", when: "The first time you tap Import from Outlook", use: "Fill blank emails and phones; add new contacts only if you choose it" },
                { scope: "Calendars.Read", when: "The first time you plan a day", use: "Read that day from your default calendar to plan around it" },
                { scope: "Calendars.ReadWrite", when: "The first time you tap Apply on a plan", use: "Create the plan’s new items as calendar events" },
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
        <h2 className="text-xl font-bold">What we keep</h2>
        <p>
          Nothing from your books. The runtime and relay are stateless: requests are processed in memory and discarded. Standard web-server access logs (IP address, path, time) are kept for up to 30 days for security.
          {PRELAUNCH_IN_BUILD && (
            <Prelaunch> If you join the early-adopter list, we keep what you typed into that form, as described next.</Prelaunch>
          )}
        </p>
      </section>

      {PRELAUNCH_IN_BUILD && (
        <Prelaunch>
          <section id="early-access" className="mt-8 scroll-mt-6 space-y-3 text-[15px] leading-relaxed">
            <h2 className="text-xl font-bold">Early-adopter list (before launch)</h2>
            <p>
              Before Accnomos opens to everyone in November 2026 you can join a list to get 3 months free at launch. Joining
              is optional and has nothing to do with using the app.
            </p>
            <ul className="list-disc space-y-2 pl-5">
              <li><strong>Who:</strong> Zaytuna Business Services Ltd, United Kingdom, is the controller of the list. Contact{" "}
                <a className="font-semibold text-teal underline" href="mailto:admin@zaytunauk.co.uk">admin@zaytunauk.co.uk</a>.</li>
              <li><strong>What we collect:</strong> your email address; your name and how you heard about us, if you give them; what the books would be for (limited company, sole trader, personal, or accountant/bookkeeper); that you ticked the consent box and its exact wording; the page you signed up on; and the date and time. We do not store your IP address with it.</li>
              <li><strong>Why:</strong> to send you <strong>one email</strong> when Accnomos launches, with your 3 months free, and to know how many people of each kind are waiting. Nothing else: no newsletter, no other products, and we never sell or share the list.</li>
              <li><strong>Lawful basis:</strong> your consent (UK GDPR Article 6(1)(a)), given by ticking the box, which is never pre-ticked. Our launch email also follows the Privacy and Electronic Communications Regulations.</li>
              <li><strong>Where it is kept:</strong> in one file on a server we run ourselves, readable only by the service operator. Nobody else receives it. If we use an email-sending service for the launch email, we will name it here first; it would act only on our instructions.</li>
              <li><strong>How long:</strong> we delete the list 12 months after launch (by the end of November 2027), except for people who have become customers. Unsubscribing deletes your entry straight away.</li>
              <li><strong>Unsubscribe or erase:</strong> reply to the launch email, or email{" "}
                <a className="font-semibold text-teal underline" href="mailto:admin@zaytunauk.co.uk">admin@zaytunauk.co.uk</a>{" "}
                from the address you signed up with. Withdrawing consent is as easy as giving it, and we will delete your entry and confirm. You can also ask for a copy of what we hold, or for it to be corrected.</li>
              <li><strong>Complaints:</strong> if you are unhappy with how we handle your data, tell us first. You also have the right to complain to the Information Commissioner&apos;s Office:{" "}
                <a className="font-semibold text-teal underline" href="https://ico.org.uk/make-a-complaint/">ico.org.uk/make-a-complaint</a>, 0303 123 1113.</li>
            </ul>
            <p>No decisions are made about you automatically, and you do not have to join the list to use Accnomos.</p>
          </section>
        </Prelaunch>
      )}

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
                { data: "Your Meta API key and AI address", where: "This device only", who: "Sent per request over HTTPS so the runtime can call the model for you; never logged or stored" },
                { data: "HMRC tokens", where: "This browser tab only", who: "Gone when the tab closes or you disconnect" },
                { data: "Device ID and VAT number", where: "This device only", who: "Sent to HMRC as fraud-prevention data when you submit" },
                { data: "Spoken questions", where: "Nowhere — converted then discarded", who: "Nobody keeps the audio" },
                { data: "Questions typed into Ask about Accnomos (the website chat)", where: "Nowhere — answered by our own model from the team's notes, then discarded; not logged", who: "Nobody; it never sees anyone's books" },
                { data: "Mail read during intake and triage", where: "Memory only; copies land in 00 Inbox and to-dos in _System/Todos", who: "You — full bodies and attachments are never fetched by triage" },
                { data: "Calendar days read for planning", where: "Memory only; applied plans in _System/Planner/applied.json", who: "You — nothing written before you tap Apply" },
                { data: "Server access logs (IP, path, time, up to 30 days)", where: "Our hosts", who: "The service operator, for security" },
              ].map((row) => (
                <tr key={row.data} className="border-t border-border align-top first:border-t-0">
                  <td className="py-2 pr-3 font-semibold">{row.data}</td>
                  <td className="py-2 pr-3">{row.where}</td>
                  <td className="py-2">{row.who}</td>
                </tr>
              ))}
              {PRELAUNCH_IN_BUILD && (
                <Prelaunch>
                  <tr className="border-t border-border align-top">
                    <td className="py-2 pr-3 font-semibold">Early-adopter list (only if you join): email, optional name, business type, how you heard, consent, time</td>
                    <td className="py-2 pr-3">One file on our server (the runtime’s data volume)</td>
                    <td className="py-2">The service operator, to send one launch email; deleted 12 months after launch</td>
                  </tr>
                </Prelaunch>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Third parties</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li>Microsoft (sign-in and OneDrive) — under your Microsoft account terms.</li>
          <li>Meta Model API — only if you provide your own key; subject to Meta&apos;s terms for your key.</li>
          <li>A hosted inference provider chosen by the server owner — only if you use your own key and the server owner has switched on the Muse Spark Open verifier; the document image is then sent there for an independent second reading. In local mode documents are never sent there.</li>
          <li>HM Revenue &amp; Customs — only if you connect HMRC.</li>
        </ul>
        <p>
          We do not sell data and we do not use advertising or analytics SDKs.
          {PRELAUNCH_IN_BUILD && <Prelaunch> The early-adopter list is not shared with anyone.</Prelaunch>}
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
          discards everything. There is no Accnomos user database.
        </p>
        <p>
          <strong>Leaving.</strong> Disconnect clears this browser&apos;s sign-in and settings; your files stay in
          your OneDrive. To delete the books, delete the Accnomos folder in your OneDrive and remove Accnomos at{" "}
          <a className="font-semibold text-teal underline" href="https://account.live.com/myapps">account.live.com/myapps</a>.
          No server-side delete is needed, because nothing from your books is stored server-side
          {PRELAUNCH_IN_BUILD ? (
            <Prelaunch>
              {" "}(the <a className="font-semibold text-teal underline" href="#early-access">early-adopter list</a> is
              separate)
            </Prelaunch>
          ) : null}
          .
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Deleting your data</h2>
        <p>
          Delete the <em>Accnomos</em> folder in your OneDrive and sign out of the app. Because we hold no copy, that removes everything.
          There is no server-side copy of your books to delete.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Contact</h2>
        <p>
          Zaytuna Business Services Ltd, United Kingdom · <a className="font-semibold text-teal underline" href="mailto:admin@zaytunauk.co.uk">admin@zaytunauk.co.uk</a>
        </p>
      </section>
    </div>
  );
}
