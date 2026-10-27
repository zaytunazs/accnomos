"use client";

/**
 * Bank statement uploads waiting for the reader: in memory only (no service
 * worker, no disk), so a reload drops them. The uploader queues files here
 * when the reader doesn't answer and flushes them on reconnect.
 */
export interface QueuedUpload {
  id: string;
  file: File;
  queuedAt: number;
  tries: number;
}

export interface FlushResult {
  id: string;
  name: string;
  ok: boolean;
  line: string;
}

let seq = 0;
const queue: QueuedUpload[] = [];
const listeners = new Set<() => void>();

function notify(): void {
  for (const fn of [...listeners]) fn();
}

/** The waiting files, oldest first. */
export function queuedUploads(): QueuedUpload[] {
  return [...queue];
}

/** Re-run `fn` on every queue change; returns an unsubscribe. */
export function subscribeQueue(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** Hold a file for later; returns its queue id. */
export function queueUpload(file: File): string {
  const id = `q${Date.now().toString(36)}-${seq++}`;
  queue.push({ id, file, queuedAt: Date.now(), tries: 0 });
  notify();
  return id;
}

function dropQueued(id: string): void {
  const i = queue.findIndex((q) => q.id === id);
  if (i >= 0) queue.splice(i, 1);
}

/**
 * Try every waiting file in order with `send`. Sent files leave the queue;
 * failures stay for the next resume. Always notifies, so the count refreshes.
 */
export async function flushUploads(send: (file: File) => Promise<string>): Promise<FlushResult[]> {
  const out: FlushResult[] = [];
  for (const q of [...queue]) {
    q.tries += 1;
    try {
      out.push({ id: q.id, name: q.file.name, ok: true, line: await send(q.file) });
      dropQueued(q.id);
    } catch (e) {
      out.push({ id: q.id, name: q.file.name, ok: false, line: `${q.file.name}: ${(e as Error).message}` });
    }
  }
  notify();
  return out;
}
