/**
 * A person at the keyboard: a visible cursor drawn into the page (headless Chromium paints no pointer), eased mouse
 * moves, a click ripple, typing at human speed and smooth scrolling. Every helper waits its own time, so a flow's
 * length on screen is the sum of what it does plus its `hold()`s.
 */
import type { Locator, Page } from "@playwright/test";

/** Injected before any page script runs; survives navigations (re-injected) and keeps its last position. */
export const CURSOR_SCRIPT = String.raw`(() => {
  if (window.__vc) return;
  const KEY = "__vc_pos";
  const touch = matchMedia("(pointer: coarse)").matches;
  let pos = { x: -100, y: -100 };
  try { pos = JSON.parse(sessionStorage.getItem(KEY) || "null") || pos; } catch {}
  const style = document.createElement("style");
  style.textContent = [
    "#__vc{position:fixed;left:0;top:0;width:" + (touch ? 44 : 30) + "px;height:" + (touch ? 44 : 30) + "px;z-index:2147483647;pointer-events:none;will-change:transform}",
    "#__vc .r{position:absolute;left:" + (touch ? 0 : -15) + "px;top:" + (touch ? 0 : -15) + "px;width:44px;height:44px;border-radius:50%;background:rgba(15,110,99,.35);transform:scale(0);opacity:0}",
    "#__vc.down .r{animation:__vcr .45s ease-out}",
    "@keyframes __vcr{0%{transform:scale(.2);opacity:1}100%{transform:scale(1.6);opacity:0}}",
    "#__vc .dot{position:absolute;left:0;top:0;width:44px;height:44px;border-radius:50%;background:rgba(27,31,36,.28);border:2px solid rgba(255,255,255,.9);box-shadow:0 2px 8px rgba(0,0,0,.25)}",
    "html.__vc-hide-caret *{caret-color:auto}",
  ].join("\n");
  const el = document.createElement("div");
  el.id = "__vc";
  el.setAttribute("aria-hidden", "true");
  // Inline too, so the cursor stays put even if the app's hydration drops the <style>.
  el.style.cssText = "position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none";
  el.innerHTML = '<div class="r"></div>' + (touch
    ? '<div class="dot"></div>'
    : '<svg width="30" height="30" viewBox="0 0 30 30"><path d="M3 2 L3 24 L9 18.5 L13 27 L17 25.2 L13 17 L21 17 Z" fill="#1b1f24" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>');
  const place = () => {
    const off = touch ? 22 : 3;
    el.style.transform = "translate(" + (pos.x - off) + "px," + (pos.y - (touch ? 22 : 2)) + "px)";
  };
  const mount = () => {
    const root = document.documentElement;
    (document.head || root).appendChild(style);
    root.appendChild(el);
    place();
    // Keep the cursor last in <html> if the app re-renders the tree.
    new MutationObserver(() => {
      if (!style.isConnected) (document.head || root).appendChild(style);
      if (el.parentNode !== root || el.nextSibling) root.appendChild(el);
    }).observe(root, { childList: true });
  };
  if (document.documentElement) mount();
  else new MutationObserver((_, mo) => { if (document.documentElement) { mo.disconnect(); mount(); } }).observe(document, { childList: true });
  addEventListener("mousemove", (e) => { if (!style.isConnected && document.head) document.head.appendChild(style); pos = { x: e.clientX, y: e.clientY }; place(); try { sessionStorage.setItem(KEY, JSON.stringify(pos)); } catch {} }, true);
  addEventListener("mousedown", () => { el.classList.remove("down"); void el.offsetWidth; el.classList.add("down"); }, true);
  window.__vc = { pos: () => pos };
})();`;

/** Hide the bits of a test-mode build that are not the product (none of these change what the app does). */
export const CLEAN_CSS = `
  nextjs-portal, [data-nextjs-toast], [data-next-badge-root] { display: none !important; }
  ::-webkit-scrollbar { width: 0 !important; height: 0 !important; }
  html { scrollbar-width: none; }
`;

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

export class Human {
  readonly page: Page;
  readonly touch: boolean;
  /** Below 1 shortens every pause and glide, to fit a busy flow into a short shot. */
  pace = 1;
  private x = -100;
  private y = -100;

  constructor(page: Page, touch = false) {
    this.page = page;
    this.touch = touch;
  }

  /** Put the cursor somewhere before recording starts (no motion on screen). */
  async park(x: number, y: number): Promise<void> {
    this.x = x;
    this.y = y;
    await this.page.mouse.move(x, y);
  }

  async hold(ms: number): Promise<void> {
    await this.page.waitForTimeout(ms * this.pace);
  }

  /** An eased glide to (x, y), about 60 frames a second; longer moves take a little longer, as a hand does. */
  async moveTo(x: number, y: number): Promise<void> {
    if (this.touch) {
      // A finger does not glide: it lifts and lands.
      this.x = x;
      this.y = y;
      await this.page.mouse.move(x, y);
      return;
    }
    const dist = Math.hypot(x - this.x, y - this.y);
    const ms = Math.min(1100, 260 + dist * 0.55) * Math.max(0.7, this.pace);
    const steps = Math.max(8, Math.round(ms / 16));
    const sx = this.x;
    const sy = this.y;
    // A slight arc, so it does not look like a robot's straight line.
    const bend = rand(-0.08, 0.08) * dist;
    for (let i = 1; i <= steps; i++) {
      const t = ease(i / steps);
      const arc = Math.sin(Math.PI * t) * bend;
      const nx = sx + (x - sx) * t + (dist ? (-(y - sy) / dist) * arc : 0);
      const ny = sy + (y - sy) * t + (dist ? ((x - sx) / dist) * arc : 0);
      await this.page.mouse.move(nx, ny);
      await this.page.waitForTimeout(16);
    }
    this.x = x;
    this.y = y;
  }

  /** Bring `target` into view smoothly if needed, then glide to a point inside it. */
  async moveToLocator(locator: Locator): Promise<{ x: number; y: number }> {
    // Pages often render a control twice (desktop and phone layouts): take the one on screen.
    const target = locator.filter({ visible: true }).first();
    await target.waitFor({ state: "visible" });
    await this.scrollIntoView(target);
    const box = await target.boundingBox();
    if (!box) throw new Error(`no box for ${target}`);
    const x = box.x + box.width * rand(0.4, 0.6);
    const y = box.y + box.height * rand(0.42, 0.58);
    await this.moveTo(x, y);
    return { x, y };
  }

  async hover(target: Locator, dwell = 600): Promise<void> {
    await this.moveToLocator(target);
    await this.hold(dwell);
  }

  async click(target: Locator, after = 450): Promise<void> {
    await this.moveToLocator(target);
    await this.hold(rand(120, 220));
    await this.page.mouse.down();
    await this.hold(rand(60, 110));
    await this.page.mouse.up();
    await this.hold(after);
  }

  /** Click a field and type into it, 55–130 ms a key with the odd pause, as a person types. */
  async type(target: Locator, text: string, after = 400): Promise<void> {
    await this.click(target, 200);
    for (const ch of text) {
      await this.page.keyboard.type(ch);
      let d = rand(55, 130);
      if (ch === " " && Math.random() < 0.15) d += rand(120, 260);
      await this.page.waitForTimeout(d);
    }
    await this.hold(after);
  }

  async press(key: string, after = 400): Promise<void> {
    await this.page.keyboard.press(key);
    await this.hold(after);
  }

  /** Scroll the page by `dy` CSS pixels over `ms`, eased (no jump). */
  async scrollBy(dy: number, ms = 900): Promise<void> {
    const start = await this.page.evaluate(() => window.scrollY);
    const steps = Math.max(10, Math.round(ms / 16));
    for (let i = 1; i <= steps; i++) {
      const y = start + dy * ease(i / steps);
      await this.page.evaluate((v) => window.scrollTo(0, v), y);
      await this.page.waitForTimeout(16);
    }
  }

  /** Scroll so `target` sits in the upper-middle of the viewport, if it is not already comfortably visible. */
  async scrollIntoView(target: Locator, ms = 800): Promise<void> {
    const box = await target.boundingBox();
    const vp = this.page.viewportSize();
    if (!box || !vp) return;
    const top = 90;
    const bottom = vp.height - 80;
    if (box.y >= top && box.y + Math.min(box.height, vp.height / 2) <= bottom) return;
    const dy = box.y - vp.height * 0.3;
    await this.scrollBy(dy, Math.min(1400, ms + Math.abs(dy) * 0.2));
  }

  async scrollToTop(ms = 700): Promise<void> {
    const y = await this.page.evaluate(() => window.scrollY);
    if (y > 0) await this.scrollBy(-y, ms);
  }
}
