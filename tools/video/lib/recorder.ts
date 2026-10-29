/**
 * Records one shot from Chromium's own compositor (CDP Page.startScreencast): JPEG frames at device resolution with
 * their timestamps, then ffmpeg turns them into constant 30 fps VP9 WebM. Sharper than Playwright's recordVideo
 * (1 Mbit VP8) and nothing is recorded while a flow sets up off camera.
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { BrowserContext, CDPSession, Page } from "@playwright/test";

export const FPS = 30;

export class Recorder {
  private cdp: CDPSession | null = null;
  private frames: { file: string; t: number }[] = [];
  private dir = "";
  private startedAt = 0;
  private pending: Promise<void>[] = [];

  private readonly context: BrowserContext;
  private readonly page: Page;
  private readonly size: { width: number; height: number };

  constructor(context: BrowserContext, page: Page, size: { width: number; height: number }) {
    this.context = context;
    this.page = page;
    this.size = size;
  }

  async start(dir: string): Promise<void> {
    this.dir = dir;
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
    this.frames = [];
    this.cdp = await this.context.newCDPSession(this.page);
    this.cdp.on("Page.screencastFrame", (f: { data: string; sessionId: number; metadata: { timestamp?: number } }) => {
      const file = path.join(dir, `f${String(this.frames.length).padStart(6, "0")}.jpg`);
      this.frames.push({ file, t: f.metadata.timestamp ?? Date.now() / 1000 });
      writeFileSync(file, Buffer.from(f.data, "base64"));
      this.pending.push(this.cdp!.send("Page.screencastFrameAck", { sessionId: f.sessionId }).then(() => undefined, () => undefined));
    });
    await this.cdp.send("Page.startScreencast", {
      format: "jpeg",
      quality: 92,
      maxWidth: this.size.width,
      maxHeight: this.size.height,
      everyNthFrame: 1,
    });
    this.startedAt = Date.now() / 1000;
    // Force a first frame even on a perfectly still page.
    await this.page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
  }

  /** Stop and encode; returns the recorded length in seconds (`padTo` holds the last frame up to that length). */
  async stop(out: string, padTo = 0): Promise<number> {
    const stoppedAt = Date.now() / 1000;
    await this.cdp?.send("Page.stopScreencast");
    await Promise.all(this.pending);
    await this.cdp?.detach().catch(() => undefined);
    this.cdp = null;
    if (!this.frames.length) throw new Error("no frames recorded");
    const t0 = Math.min(this.startedAt, this.frames[0]!.t);
    const end = Math.max(stoppedAt, t0 + padTo);
    // ffmpeg's concat demuxer with per-frame durations: the screencast only sends a frame when something changed.
    const lines: string[] = ["ffconcat version 1.0"];
    this.frames.forEach((f, i) => {
      const next = i + 1 < this.frames.length ? this.frames[i + 1]!.t : end;
      const startT = i === 0 ? t0 : f.t;
      lines.push(`file '${path.basename(f.file)}'`, `duration ${Math.max(0.001, next - startT).toFixed(4)}`);
    });
    lines.push(`file '${path.basename(this.frames.at(-1)!.file)}'`); // concat needs the last file twice to honour its duration
    const list = path.join(this.dir, "frames.ffconcat");
    writeFileSync(list, lines.join("\n") + "\n");
    const { width, height } = this.size;
    const r = spawnSync(
      "ffmpeg",
      [
        "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", list,
        "-vf", `scale=${width}:${height}:flags=lanczos:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=0xf4f3ee,fps=${FPS},format=yuv420p`,
        "-c:v", "libvpx-vp9", "-crf", "28", "-b:v", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4",
        "-an", out,
      ],
      { stdio: "inherit" },
    );
    if (r.status !== 0) throw new Error(`ffmpeg failed for ${out}`);
    rmSync(this.dir, { recursive: true, force: true });
    return end - t0;
  }
}
