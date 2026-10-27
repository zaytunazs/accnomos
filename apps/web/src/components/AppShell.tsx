import type { ReactNode } from "react";
import AppNav from "./AppNav";
import DemoBanner from "./DemoBanner";

function LogoMark() {
  return (
    <span
      aria-hidden="true"
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-teal"
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path
          d="M10 2.5 16.5 6v8L10 17.5 3.5 14V6L10 2.5Z"
          stroke="#F4F3EE"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path
          d="M7 10.2l2.1 2.1L13.2 8"
          stroke="#F4F3EE"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <DemoBanner />
      <div className="flex flex-1 flex-col min-[900px]:flex-row">
        <aside className="flex w-full shrink-0 flex-col gap-6 border-b border-border bg-white p-5 min-[900px]:w-[232px] min-[900px]:border-b-0 min-[900px]:border-r">
          <div className="flex items-center gap-2.5">
            <LogoMark />
            <span className="text-lg font-extrabold tracking-tight">
              Accnomos
            </span>
          </div>
          <AppNav />
          <div className="mt-auto flex flex-col gap-3">
            <p className="rounded-2xl bg-ground p-4 text-sm leading-6 text-muted">
              Your books live in OneDrive — Apps / Accnomos
            </p>
            <p className="flex items-center gap-2 text-sm font-semibold text-muted">
              <span
                aria-hidden="true"
                className="h-2 w-2 rounded-full bg-teal"
              />
              AI: local Meta agent (Glimmer 30B)
            </p>
          </div>
        </aside>
        <main className="min-w-0 flex-1 px-4 py-8 sm:px-8">
          <div className="mx-auto w-full max-w-3xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
