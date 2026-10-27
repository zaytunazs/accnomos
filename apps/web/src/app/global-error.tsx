"use client";

import { useEffect, useState } from "react";
import { copyText } from "@/components/ErrorDetails";

/**
 * The last-resort page: the root layout itself failed, so this replaces it and
 * cannot use the app's styles, links or context. Plain anchor, inline styles,
 * and only the runtime correlation id read off the message (lib/runtime.ts
 * errorDetail appends it as "· ref …").
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    console.error(error);
  }, [error]);

  const ref = /(?:·|\|) ref ([A-Za-z0-9_-]+)/.exec(error.message)?.[1] ?? null;
  const detail = error.message
    .replace(/\s*\(status \d{3}(?:\s*· ref [A-Za-z0-9_-]+)?\)\s*$/, "")
    .trim();

  async function copy() {
    const lines = ["Accnomos went wrong", detail || "The whole page failed to load."];
    if (ref) lines.push(`Reference: ${ref}`);
    if (error.digest) lines.push(`Error digest: ${error.digest}`);
    lines.push(`Page: ${window.location.href}`, `Time: ${new Date().toISOString()}`);
    setCopied(await copyText(lines.join("\n")));
  }

  const card: React.CSSProperties = {
    maxWidth: "42rem",
    margin: "3rem auto",
    padding: "1.5rem",
    border: "1px solid #e3e1d8",
    borderRadius: "1rem",
    background: "#fff",
    color: "#1b1f24",
    fontFamily: "system-ui, sans-serif",
  };
  const button: React.CSSProperties = {
    display: "inline-block",
    padding: "0.65rem 1rem",
    borderRadius: "0.75rem",
    border: "1px solid #e3e1d8",
    background: "#fff",
    color: "#0a4f47",
    fontWeight: 700,
    fontSize: "15px",
    textDecoration: "none",
    cursor: "pointer",
  };
  const primary: React.CSSProperties = { ...button, background: "#0f6e63", borderColor: "#0f6e63", color: "#fff" };

  return (
    <html lang="en">
      <body style={{ background: "#f4f3ee", margin: 0 }}>
        <div style={card}>
          <h1 style={{ margin: 0, fontSize: "1.75rem" }}>Something went wrong</h1>
          <p style={{ color: "#4b5159", lineHeight: 1.75 }}>{detail || "The whole page failed to load — nothing is lost."}</p>
          {ref ? (
            <p>
              Quote this reference: <code style={{ background: "#f4f3ee", padding: "0.1rem 0.4rem" }}>{ref}</code>
            </p>
          ) : null}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "1rem" }}>
            <button type="button" onClick={reset} style={primary}>
              Try again
            </button>
            {/* No app router this deep: a full navigation, not a Link. */}
            <button type="button" onClick={() => window.location.assign("/")} style={button}>
              Back to Home
            </button>
            <button type="button" onClick={copy} style={button}>
              {copied ? "Copied" : "Copy details"}
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
