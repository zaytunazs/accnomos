import Link from "next/link";

/**
 * The one sign-in call to action, same component and same destination (/connect) on every page.
 * Home names the destination ("Connect your OneDrive"); every other page uses "Sign in to see your books".
 */
export default function SignInCta({ home = false, className }: { home?: boolean; className?: string }) {
  return (
    <Link
      href="/connect"
      className={
        className ??
        "shrink-0 whitespace-nowrap rounded-xl bg-teal px-4 py-2.5 text-sm font-bold text-white hover:bg-teal-dark"
      }
    >
      {home ? "Connect your OneDrive" : "Sign in to see your books"}
    </Link>
  );
}
