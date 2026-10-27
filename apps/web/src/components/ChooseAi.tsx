"use client";

import { useEffect, useState } from "react";
import {
  DEFAULT_KEY,
  DEFAULT_LOCAL,
  loadAiConfig,
  RUNTIME_URL,
  saveAiConfig,
  saveAiTest,
  type AiConfig,
  type AiMode,
} from "@/lib/ai-config";
import { runtimeAiTest, type RtAiTest } from "@/lib/runtime";

type TestResult = RtAiTest;

export default function ChooseAi() {
  const [mode, setMode] = useState<AiMode>("local");
  const [local, setLocal] = useState<AiConfig>(DEFAULT_LOCAL);
  const [key, setKey] = useState<AiConfig>(DEFAULT_KEY);
  const [result, setResult] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const cfg = loadAiConfig();
    if (!cfg) return;
    // Defer to avoid a synchronous setState in the effect body.
    queueMicrotask(() => {
      setMode(cfg.mode);
      if (cfg.mode === "local") setLocal(cfg);
      else setKey(cfg);
      setSaved(true);
    });
  }, []);

  const current = mode === "local" ? local : key;

  async function test() {
    setTesting(true);
    setResult(null);
    try {
      const r = await runtimeAiTest(current);
      setResult(r);
      saveAiTest(current, r.ok); // Home's setup checklist reads this, next to the saved config
    } catch (e) {
      setResult({ ok: false, mode, detail: `Could not reach the runtime at ${RUNTIME_URL}: ${(e as Error).message}` });
      saveAiTest(current, false);
    } finally {
      setTesting(false);
    }
  }

  function save() {
    saveAiConfig(current);
    setSaved(true);
  }

  const card = (active: boolean) =>
    `block w-full rounded-2xl border bg-white p-4 text-left ${active ? "border-2 border-[#0F6E63]" : "border-[#E3E1D8]"}`;
  const input = "mt-1 h-11 w-full rounded-xl border border-[#D9D6CC] bg-[#F9F8F4] px-3 text-[15px] text-[#1B1F24]";

  return (
    <div className="mt-6 space-y-4">
      <button type="button" onClick={() => setMode("local")} className={card(mode === "local")} aria-pressed={mode === "local"}>
        <div className="flex items-center justify-between">
          <span className="text-[17px] font-extrabold">On my own machine</span>
          <span className="rounded-full bg-[#E6F1EF] px-2 py-0.5 text-[11px] font-extrabold text-[#0A4F47]">MOST PRIVATE</span>
        </div>
        <p className="mt-1 text-sm text-[#4B5159]">
          Muse Glimmer 30B, open weights, running on your computer. Receipts never leave your network.
        </p>
      </button>
      {mode === "local" && (
        <div className="rounded-2xl border border-[#E3E1D8] bg-white p-4">
          <label className="text-xs font-bold text-[#4B5159]" htmlFor="agent">Local agent address (Ollama)</label>
          <input id="agent" className={input} value={local.baseUrl} onChange={(e) => setLocal({ ...local, baseUrl: e.target.value })} />
          <label className="mt-3 block text-xs font-bold text-[#4B5159]" htmlFor="lmodel">Model</label>
          <input id="lmodel" className={input} value={local.model} onChange={(e) => setLocal({ ...local, model: e.target.value })} />
        </div>
      )}

      <button type="button" onClick={() => setMode("key")} className={card(mode === "key")} aria-pressed={mode === "key"}>
        <span className="text-[17px] font-extrabold">My own Meta API key</span>
        <p className="mt-1 text-sm text-[#4B5159]">
          Muse Spark via the Meta Model API. Fast, no hardware needed. Standard tier — not used for training.
        </p>
      </button>
      {mode === "key" && (
        <div className="rounded-2xl border border-[#E3E1D8] bg-white p-4">
          <label className="text-xs font-bold text-[#4B5159]" htmlFor="apikey">API key</label>
          <input
            id="apikey"
            type="password"
            autoComplete="off"
            placeholder="Paste your key"
            className={input}
            value={key.apiKey ?? ""}
            onChange={(e) => setKey({ ...key, apiKey: e.target.value })}
          />
          <p className="mt-2 text-xs text-[#4B5159]">
            Stored in this browser only and sent straight to your runtime.{" "}
            <a className="font-bold text-[#0F6E63]" href="https://dev.meta.ai" target="_blank" rel="noreferrer">Get a key at dev.meta.ai</a>
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={test} disabled={testing} className="h-12 rounded-xl border border-[#D9D6CC] bg-white px-5 text-[15px] font-bold disabled:opacity-60">
          {testing ? "Testing…" : "Test connection"}
        </button>
        <button type="button" onClick={save} className="h-12 flex-1 rounded-xl bg-[#0F6E63] px-5 text-[15px] font-extrabold text-white">
          {saved ? "Saved · Continue" : "Save and continue"}
        </button>
      </div>

      {result && (
        <div
          role="status"
          className={`rounded-2xl border p-4 text-sm ${result.ok ? "border-[#0F6E63] bg-[#E6F1EF] text-[#0A4F47]" : "border-[#F3C892] bg-[#FFF7ED] text-[#8A3F06]"}`}
        >
          <strong>{result.ok ? "Connected" : "Not connected"}</strong>
          {result.model ? ` · ${result.model}` : ""} · {result.detail}
        </div>
      )}
    </div>
  );
}
