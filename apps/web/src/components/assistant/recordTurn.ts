"use client";

import { decide, SPEECH_LEVEL } from "@/lib/handsfree";

const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

function pickType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t));
}

export class MicError extends Error {}

/**
 * One hands-free turn: record from the microphone until the speaker stops (lib/handsfree.ts `decide`), with the
 * level reported for the meter. Resolves to the recording, or null when nothing was said (or `signal` aborted).
 * Nothing leaves the browser here; the caller uploads the recording.
 */
export async function recordTurn(onLevel: (level: number) => void, signal: AbortSignal): Promise<Blob | null> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    throw new MicError("This browser can't record audio. Type your question instead.");
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch {
    throw new MicError("Microphone access was refused. Allow it in your browser's site settings, or type instead.");
  }
  if (signal.aborted) {
    stream.getTracks().forEach((t) => t.stop());
    return null;
  }
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);
  const type = pickType();
  const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => {
    if (e.data.size) chunks.push(e.data);
  };

  return new Promise<Blob | null>((resolve) => {
    const started = performance.now();
    let heard: number | null = null;
    let outcome: "end" | "empty" = "empty";
    let timer = 0;
    const finish = (how: "end" | "empty") => {
      if (timer === 0) return;
      window.clearInterval(timer);
      timer = 0;
      outcome = how;
      signal.removeEventListener("abort", onAbort);
      if (rec.state === "recording") rec.stop();
      else done();
    };
    const done = () => {
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close().catch(() => {});
      onLevel(0);
      resolve(outcome === "end" && chunks.length ? new Blob(chunks, { type: rec.mimeType || type || "audio/webm" }) : null);
    };
    const onAbort = () => finish("empty");
    rec.onstop = done;
    signal.addEventListener("abort", onAbort);
    timer = window.setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += ((s - 128) / 128) ** 2;
      const level = Math.min(1, Math.sqrt(sum / samples.length) * 4);
      onLevel(level);
      const now = performance.now();
      if (level >= SPEECH_LEVEL) heard = now;
      const next = decide(now, started, heard);
      if (next !== "continue") finish(next);
    }, 60);
    rec.start(250);
  });
}

/** Read an answer aloud (the browser's own voice, en-GB where it has one). Resolves when done or stopped. */
export function speak(text: string, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth || !text) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-GB";
    const voice = synth.getVoices().find((v) => v.lang === "en-GB");
    if (voice) u.voice = voice;
    const end = () => {
      signal.removeEventListener("abort", stop);
      resolve();
    };
    const stop = () => {
      synth.cancel();
      end();
    };
    u.onend = end;
    u.onerror = end;
    signal.addEventListener("abort", stop);
    synth.cancel();
    synth.speak(u);
  });
}
