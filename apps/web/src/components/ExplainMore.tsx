import Link from "next/link";
import type { ReactNode } from "react";
import Explain from "./Explain";

interface ExplainMoreProps {
  /** Short label used in the button's accessible name and the drawer heading. */
  title: string;
  /** Anchor on /how-it-works with the full section, without the leading #. */
  anchor: string;
  children: ReactNode;
}

/** One-paragraph drawer plus a “Read more” anchor into /how-it-works. */
export default function ExplainMore({ title, anchor, children }: ExplainMoreProps) {
  return (
    <Explain title={title}>
      <p>{children}</p>
      <p>
        <Link href={`/how-it-works#${anchor}`} className="font-bold text-teal-dark underline hover:text-teal">
          Read more
        </Link>
      </p>
    </Explain>
  );
}
