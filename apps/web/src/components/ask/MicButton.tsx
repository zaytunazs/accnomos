"use client";

import { useEffect, useRef, useState } from "react";

const MIN_MS = 400; // shorter than this is a tap, not a question
const MAX_MS = 60_000; // a question, not a voice memo; the runtime allows 10 minutes
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

function pickType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t));
}

interface Props {
  disabled: boolean;
  /** Why it's disabled, shown as the tooltip. */
  reason?: string;
  onRecorded: (audio: Blob) => void;
  onError: (message: string) => void;
}

/** Hold to talk: MediaRecorder (webm/opus where supported) with a live level meter. Nothing is uploaded until release. */
export default function MicButton({ disabled, reason, onRecorded, onError }: Props) {
  const [recording, setRecording] = useState(false);
  const [level, setLevel] = useState(0);
  const rec = useRef<MediaRecorder | null>(null);
  const started = useRef(0);
  const holding = useRef(false);
  const cleanup = useRef<() => void>(() => {});

  useEffect(() => () => cleanup.current(), []);

  async function start() {
    if (disabled || rec.current) return;
    holding.current = true;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      return onError("This browser can't record audio.");
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      return onError("Microphone access was refused. Allow it in your browser's site settings to ask by voice.");
    }
    if (!holding.current) {
      // released while the permission prompt was open
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    let frame = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += ((s - 128) / 128) ** 2;
      setLevel(Math.min(1, Math.sqrt(sum / samples.length) * 4));
      frame = requestAnimationFrame(tick);
    };
    tick();
    const limit = window.setTimeout(stop, MAX_MS);

    const type = pickType();
    const r = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    r.onstop = () => {
      cleanup.current();
      const ms = Date.now() - started.current;
      if (ms < MIN_MS) return onError("Hold the mic button while you speak, then let go.");
      onRecorded(new Blob(chunks, { type: r.mimeType || type || "audio/webm" }));
    };
    cleanup.current = () => {
      window.clearTimeout(limit);
      cancelAnimationFrame(frame);
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close().catch(() => {});
      rec.current = null;
      cleanup.current = () => {};
      setRecording(false);
      setLevel(0);
    };
    rec.current = r;
    started.current = Date.now();
    r.start();
    setRecording(true);
  }

  function stop() {
    holding.current = false;
    if (rec.current?.state === "recording") rec.current.stop();
  }

  return (
    // the tooltip sits on the wrapper too: some browsers don't show a disabled button's title
    <div className="flex shrink-0 items-center gap-2" title={disabled ? reason : undefined}>
      {recording && (
        <div className="flex h-8 items-end gap-[3px]" aria-hidden="true">
          {[0.5, 0.8, 1, 0.8, 0.5].map((w, i) => (
            <span
              key={i}
              className="w-1 rounded-full bg-teal transition-[height] duration-75"
              style={{ height: `${Math.max(12, level * w * 100)}%` }}
            />
          ))}
        </div>
      )}
      <button
        type="button"
        disabled={disabled}
        title={disabled ? reason : recording ? "Release to send" : "Hold to ask by voice"}
        aria-label={recording ? "Recording — release to send" : "Hold to ask by voice"}
        aria-pressed={recording}
        onPointerDown={(e) => {
          e.preventDefault();
          e.currentTarget.setPointerCapture(e.pointerId);
          void start();
        }}
        onPointerUp={stop}
        onPointerCancel={stop}
        onKeyDown={(e) => {
          if ((e.key === " " || e.key === "Enter") && !e.repeat) {
            e.preventDefault();
            void start();
          }
        }}
        onKeyUp={(e) => {
          if (e.key === " " || e.key === "Enter") stop();
        }}
        onContextMenu={(e) => e.preventDefault()}
        className={`flex h-14 w-14 touch-none select-none items-center justify-center rounded-xl border text-ink disabled:cursor-not-allowed disabled:opacity-40 ${
          recording ? "border-teal bg-teal text-white" : "border-border bg-white hover:border-teal"
        }`}
      >
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <rect x="9" y="3" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}
