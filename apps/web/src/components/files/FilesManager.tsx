"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountInfo } from "@azure/msal-browser";
import ArchiveYears from "@/components/files/ArchiveYears";
import BackupsPanel from "@/components/files/BackupsPanel";
import FileSearch from "@/components/files/FileSearch";
import StorageOverview from "@/components/files/StorageOverview";
import { reason } from "@/components/files/manage";
import { LoadingSkeleton, RuntimeErrorNote } from "@/components/States";
import { filesApi, type RtFileIndex, type RtStorageOverview } from "@/lib/runtime";

/** Storage, search, archive and backups for the signed-in books (services/runtime/app/routes_files.py). */
export default function FilesManager({ account, onTreeChanged }: { account: AccountInfo; onTreeChanged: () => void }) {
  const [overview, setOverview] = useState<RtStorageOverview | null>(null);
  const [index, setIndex] = useState<RtFileIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [cleanNote, setCleanNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, i] = await Promise.all([filesApi.overview(account), filesApi.index(account)]);
      setOverview(o);
      setIndex(i);
      setError(null);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(reason(e));
    }
  }, [account]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  const changed = useCallback(() => {
    void load();
    onTreeChanged();
  }, [load, onTreeChanged]);

  return (
    <div className="flex min-w-0 flex-col gap-3">
      {error ? (
        <RuntimeErrorNote message={error} title="Couldn't read your storage" onRetry={() => void load()} />
      ) : !overview || !index ? (
        <LoadingSkeleton lines={3} label="Adding up your storage…" />
      ) : (
        <>
          <StorageOverview
            key={`o${version}`}
            account={account}
            overview={overview}
            onChanged={changed}
            note={cleanNote}
            setNote={setCleanNote}
          />
          <FileSearch account={account} index={index} onChanged={changed} />
        </>
      )}
      <ArchiveYears account={account} onChanged={changed} />
      <BackupsPanel account={account} onChanged={changed} />
    </div>
  );
}
