import Link from "next/link";
import { inlineParts } from "@/lib/help";

/** An article's text: **bold** and [links](/path) only; everything else is plain text. */
export default function Rich({ text }: { text: string }) {
  return (
    <>
      {inlineParts(text).map((p, i) =>
        p.kind === "bold" ? (
          <strong key={i}>{p.text}</strong>
        ) : p.kind === "link" ? (
          <Link key={i} href={p.href} className="font-bold text-teal-dark underline underline-offset-2">
            {p.text}
          </Link>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
