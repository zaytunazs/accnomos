"use client";

import Link from "next/link";
import FullBackupPanel from "@/components/files/FullBackupPanel";
import PreviousFiles from "@/components/files/PreviousFiles";
import { useAccount } from "@/components/jobs/useAccount";

/** Settings › Files & backups: Back up now (a full, dated backup apart from the books) and earlier files never read.
 *  The Files page has the same two panels beside storage, search, archive and the _System zips. */
export default function FilesBackups({ card, heading }: { card: string; heading: string }) {
  const account = useAccount();
  if (account === undefined) return <p className="text-sm text-muted">Loading…</p>;
  if (account === null) {
    return (
      <section aria-labelledby="settings-files-heading" className={card}>
        <h2 id="settings-files-heading" className={heading}>
          Files &amp; backups
        </h2>
        <p className="mt-2 text-sm text-muted">Sign in with Microsoft to back up your books or look for earlier files.</p>
      </section>
    );
  }
  return (
    <div className="space-y-4">
      <FullBackupPanel account={account} />
      <PreviousFiles account={account} />
      <p className="text-sm text-muted">
        Storage, search, archive by year and the smaller _System backups are on the{" "}
        <Link href="/files" className="font-bold text-teal-dark underline underline-offset-2">
          Files page
        </Link>
        .
      </p>
    </div>
  );
}
