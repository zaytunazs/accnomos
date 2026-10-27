export const metadata = { title: "Privacy policy — Accnomos" };

const UPDATED = "27 October 2026";

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-10 text-ink">
      <h1 className="text-3xl font-extrabold tracking-tight">Privacy policy</h1>
      <p className="mt-2 text-sm text-muted">Accnomos · Zaytuna Business Services Ltd · last updated {UPDATED}</p>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">The short version</h2>
        <p>
          Accnomos keeps your books in <strong>your own Microsoft OneDrive</strong>. We do not run a user database and we
          do not store your receipts, invoices, ledger or VAT figures on our servers. The AI that reads your documents runs
          either on a machine you control or through an API key you provide.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">What the app accesses</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li><strong>Microsoft account (sign-in):</strong> your name and e-mail, used only to show who is signed in.</li>
          <li><strong>OneDrive app folder:</strong> the app reads and writes files inside its own <em>Accnomos</em> folder (inbox, ledger events, Books.xlsx, VAT returns). It does not read the rest of your drive.</li>
          <li><strong>Sending invoices (Outlook, optional):</strong> the first time you send an invoice or a payment reminder, the app asks Microsoft for permission to send mail as you (<code>Mail.Send</code>). It sends only the email you saw and confirmed, to the address you confirmed, with the invoice PDF attached; a copy is in your Sent Items and the PDF in your <em>Accnomos</em> folder. Reminder wording is drafted by your own AI connection from the invoice number, amount and dates; your bank details are not sent to the AI.</li>
          <li><strong>Camera / photos (Android):</strong> only when you choose to capture or pick a receipt; the image is uploaded to your OneDrive inbox.</li>
          <li><strong>Your AI connection:</strong> either the address of a model running on your own hardware (e.g. Muse Glimmer on Ollama), or a Meta Model API key you paste in. The key is stored on your device and sent only to our stateless runtime over HTTPS to make the request on your behalf; it is never logged or stored server-side.</li>
          <li><strong>HMRC (sandbox during the hackathon):</strong> if you connect HMRC, the OAuth tokens stay in your browser session. Our relay holds only the HMRC application secret and forwards requests; it stores nothing about you. HMRC requires fraud-prevention headers (device, screen size, time zone, IP address) which the relay forwards with each request.</li>
        </ul>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">What we keep</h2>
        <p>
          Nothing personal. The runtime and relay are stateless: requests are processed in memory and discarded. Standard web-server access logs (IP address, path, time) are kept for up to 30 days for security.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Third parties</h2>
        <ul className="list-disc space-y-2 pl-5">
          <li>Microsoft (sign-in and OneDrive) — under your Microsoft account terms.</li>
          <li>Meta Model API — only if you provide your own key; subject to Meta&apos;s terms for your key.</li>
          <li>Baseten — only if you use your own key and the server owner has switched on the Muse Spark Open verifier; the document image is then sent there for an independent second reading. In local mode documents are never sent to Baseten.</li>
          <li>HM Revenue &amp; Customs — only if you connect HMRC.</li>
        </ul>
        <p>We do not sell data and we do not use advertising or analytics SDKs.</p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Deleting your data</h2>
        <p>
          Delete the <em>Accnomos</em> folder in your OneDrive and sign out of the app. Because we hold no copy, that removes everything.
        </p>
      </section>

      <section className="mt-8 space-y-3 text-[15px] leading-relaxed">
        <h2 className="text-xl font-bold">Contact</h2>
        <p>
          Zaytuna Business Services Ltd, United Kingdom · <a className="font-semibold text-teal underline" href="mailto:admin@zaytunauk.co.uk">admin@zaytunauk.co.uk</a>
        </p>
      </section>
    </main>
  );
}
