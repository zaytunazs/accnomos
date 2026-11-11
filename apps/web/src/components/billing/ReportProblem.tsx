"use client";

import { useEffect, useState } from "react";
import Modal, { fieldArea, fieldLabel, primaryButton, secondaryButton } from "@/components/invoices/Modal";
import { useAccount } from "@/components/jobs/useAccount";
import { supportApi } from "@/lib/billing-api";
import { REPORT_PROBLEM_EVENT, reportClosed, reportRequested } from "@/lib/report-problem";
import { APP_VERSION } from "@/lib/version";


const MAX_SHOT = 1_500_000; // bytes: the runtime refuses anything very large

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ""));
    r.onerror = () => reject(new Error("Could not read that file."));
    r.readAsDataURL(file);
  });
}

/** Help › Report a problem: a message and, if you like, a screenshot from your device. Sends the page, app version and browser. */
export default function ReportProblem() {
  const account = useAccount();
  const [open, setOpenState] = useState(() => reportRequested());
  const setOpen = (v: boolean) => {
    if (!v) reportClosed();
    setOpenState(v);
  };
  const [message, setMessage] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(() => window.location.pathname);

  useEffect(() => {
    const on = () => {
      setPage(window.location.pathname);
      setMessage("");
      setFile(null);
      setError(null);
      setState("idle");
      setOpen(true);
    };
    window.addEventListener(REPORT_PROBLEM_EVENT, on);
    return () => window.removeEventListener(REPORT_PROBLEM_EVENT, on);
  }, []);

  if (!open) return null;

  async function send() {
    if (!account) return setError("Sign in first, so we can reply.");
    if (message.trim().length < 5) return setError("Tell us a little about what went wrong.");
    if (file && file.size > MAX_SHOT) return setError("That screenshot is too large: choose one under 1.5 MB.");
    setState("sending");
    setError(null);
    try {
      await supportApi.bugReport(account, {
        message: message.trim(),
        page,
        app: "web",
        version: APP_VERSION,
        ua: navigator.userAgent,
        ...(file ? { screenshot_b64: await readAsBase64(file) } : {}),
      });
      setState("sent");
    } catch (e) {
      setError((e as Error).message);
      setState("idle");
    }
  }

  return (
    <Modal id="report-problem-title" title="Report a problem" onClose={() => setOpen(false)}>
      {state === "sent" ? (
        <div>
          <p role="status" className="mt-3 text-[15px] text-ink">Thank you. We have your report and will look at it.</p>
          <button type="button" className={`${primaryButton} mt-4`} onClick={() => setOpen(false)}>Close</button>
        </div>
      ) : (
        <form
          className="mt-3 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <label className="block">
            <span className={fieldLabel}>What went wrong?</span>
            <textarea className={fieldArea} rows={5} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={4000} />
          </label>
          <label className="block">
            <span className={fieldLabel}>Screenshot (optional)</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" className="mt-1 block w-full text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <p className="text-xs text-muted">
            We send this message, the page you are on ({page}), the app version and your browser. A screenshot is sent only if you choose one: check it shows nothing private.
          </p>
          {error && <p role="alert" className="text-sm font-bold text-red-700">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="submit" className={primaryButton} disabled={state === "sending"}>{state === "sending" ? "Sending…" : "Send report"}</button>
            <button type="button" className={secondaryButton} onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
