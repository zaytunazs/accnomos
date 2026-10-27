"use client";

import { usePathname } from "next/navigation";
import SignInCta from "@/components/SignInCta";
import { useSignedIn } from "@/lib/signed-in";

/**
 * The fictional-company banner. The single "SAMPLE — FICTIONAL COMPANY" label on every signed-out
 * page (sample fallbacks elsewhere on the page never repeat those words): shown until this device
 * is known to be signed in, hidden once it is. The sign-in button is omitted on the /connect pages,
 * which are the button's destination.
 */
export default function DemoBanner() {
  const path = usePathname() ?? "/";
  const signedIn = useSignedIn(path);

  if (signedIn === true) return null;
  const onConnect = path === "/connect" || path.startsWith("/connect/");
  return (
    <aside aria-label="Sample data">
      <p className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-ink px-4 py-2 text-center text-[13px] font-bold text-ground">
        <span>SAMPLE — FICTIONAL COMPANY · demo data only</span>
        {!onConnect && (
          <span className="inline-flex items-center gap-2 font-normal">
            <span aria-hidden="true">·</span>
            <SignInCta
              home={path === "/"}
              className="font-bold text-ground underline underline-offset-2"
            />
          </span>
        )}
      </p>
    </aside>
  );
}
