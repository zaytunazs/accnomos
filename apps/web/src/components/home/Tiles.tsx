import Link from "next/link";
import { tiles } from "@/lib/sample-home";

export default function Tiles() {
  return (
    <div className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 min-[1100px]:grid-cols-4">
      {tiles.map((tile) => {
        const warn = tile.tone === "warn";
        return (
          <div
            key={tile.label}
            className={`rounded-2xl border p-4 ${
              warn
                ? "border-warn-border bg-warn-bg"
                : "border-border bg-white"
            }`}
          >
            <p
              className={`text-sm font-semibold ${
                warn ? "text-warn-ink" : "text-muted"
              }`}
            >
              {tile.label}
            </p>
            <p
              className={`mt-1 text-2xl font-extrabold tracking-tight ${
                warn ? "text-warn-ink" : "text-ink"
              }`}
            >
              {tile.value}
            </p>
            {warn ? (
              <Link
                href="/review"
                className="mt-1 inline-block text-sm font-bold text-warn-ink underline"
              >
                {tile.sub}
              </Link>
            ) : (
              <p
                className={`mt-1 text-[13px] font-semibold ${
                  tile.tone === "amber" ? "text-amber" : "text-muted"
                }`}
              >
                {tile.sub}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
