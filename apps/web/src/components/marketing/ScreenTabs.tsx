"use client";

import { useRef, useState } from "react";
import { BrowserFrame } from "./Marks";

const SCREENS = [
  {
    id: "invoices",
    label: "Invoices",
    src: "/shots/feat-invoices.webp",
    width: 808,
    height: 550,
    alt: "Invoices: a draft for Harrogate Dental Ltd, £1,860; one 26 days overdue for Acme Kitchens Ltd, £405; one paid by Leeds Lettings, £960.",
  },
  {
    id: "reports",
    label: "Reports",
    src: "/shots/feat-reports.webp",
    width: 808,
    height: 750,
    alt: "Reports: profit and loss for Jul–Sep 2026 compared with earlier periods, with sales, cost of sales, gross profit and overheads.",
  },
  {
    id: "contacts",
    label: "Contacts",
    src: "/shots/feat-contacts.webp",
    width: 888,
    height: 750,
    alt: "Contacts: customers and suppliers from the books, with Acme Kitchens Ltd open showing payment terms and £540 owed.",
  },
  {
    id: "files",
    label: "Your OneDrive folder",
    src: "/shots/feat-files.webp",
    width: 808,
    height: 560,
    alt: "Files: the Accnomos folder in OneDrive, from 00 Inbox to 07 Reports, README.txt and the _System folder with the ledger.",
  },
];

/** A small tabbed viewer of real screens (sample books). Arrow keys move between tabs (WAI-ARIA tabs pattern). */
export default function ScreenTabs() {
  const [active, setActive] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKey = (e: React.KeyboardEvent, i: number) => {
    const next =
      e.key === "ArrowRight" ? (i + 1) % SCREENS.length
      : e.key === "ArrowLeft" ? (i - 1 + SCREENS.length) % SCREENS.length
      : e.key === "Home" ? 0
      : e.key === "End" ? SCREENS.length - 1
      : null;
    if (next === null) return;
    e.preventDefault();
    setActive(next);
    tabs.current[next]?.focus();
  };

  return (
    <div>
      <div role="tablist" aria-label="Screens from the sample books" className="flex flex-wrap gap-2">
        {SCREENS.map((s, i) => (
          <button
            key={s.id}
            ref={(el) => {
              tabs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`screen-tab-${s.id}`}
            aria-selected={i === active}
            aria-controls={`screen-panel-${s.id}`}
            tabIndex={i === active ? 0 : -1}
            onClick={() => setActive(i)}
            onKeyDown={(e) => onKey(e, i)}
            className={`rounded-full px-4 py-2 text-sm font-bold ${
              i === active ? "bg-ink text-ground" : "bg-white text-muted hover:text-ink"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>
      {SCREENS.map((s, i) => (
        <div
          key={s.id}
          role="tabpanel"
          id={`screen-panel-${s.id}`}
          aria-labelledby={`screen-tab-${s.id}`}
          hidden={i !== active}
          className="mt-4"
        >
          <BrowserFrame className="screen-in">
            <div className="max-h-[440px] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element -- static export, unoptimised images */}
              <img
                src={s.src}
                alt={s.alt}
                width={s.width}
                height={s.height}
                loading="lazy"
                decoding="async"
                className="block h-auto w-full"
              />
            </div>
          </BrowserFrame>
        </div>
      ))}
    </div>
  );
}
