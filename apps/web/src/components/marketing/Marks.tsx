/**
 * The Accnomos mark (4 Nov 2026, Zaytuna brand): an olive branch whose stem is a tick, with a gold smile under it, on a
 * Zaytuna-brown tile. `className` adds classes to the tile (e.g. a ring on dark bands); `stroke` is kept for old call
 * sites and ignored: the mark has its own colours. Masters: public/brand/zaytuna/icon.svg (and icon-small.svg).
 */
export function LogoMark({ className = "" }: { className?: string; stroke?: string }) {
  return (
    <span aria-hidden="true" className={`flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg ${className}`}>
      <svg width="36" height="36" viewBox="0 0 108 108" role="presentation">
        <rect width="108" height="108" rx="24" fill="#5A2D00" />
        <path
          d="M33 50c8 6 14 12 18 20 7-21 17-35 25-45"
          fill="none"
          stroke="#F4EDE5"
          strokeWidth="7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <ellipse cx="45" cy="38" rx="5.5" ry="12" transform="rotate(-40 45 38)" fill="#C9A45C" />
        <ellipse cx="64" cy="32" rx="5" ry="11" transform="rotate(35 64 32)" fill="#C9A45C" />
        <ellipse cx="72" cy="49" rx="4.5" ry="10" transform="rotate(70 72 49)" fill="#8A9A3B" />
        <path d="M32 78q22 16 44 0" fill="none" stroke="#C9A45C" strokeWidth="6.5" strokeLinecap="round" />
      </svg>
    </span>
  );
}

/** A browser window around a real screenshot: grey dots and a blank address bar (no made-up URL). */
export function BrowserFrame({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`overflow-hidden rounded-xl border border-black/10 bg-white shadow-frame ${className}`}>
      <div aria-hidden="true" className="flex h-7 items-center gap-1.5 border-b border-black/5 bg-[#ecebe5] px-3">
        <span className="h-2.5 w-2.5 rounded-full bg-black/15" />
        <span className="h-2.5 w-2.5 rounded-full bg-black/15" />
        <span className="h-2.5 w-2.5 rounded-full bg-black/15" />
        <span className="ml-3 h-3.5 flex-1 rounded-full bg-white/80" />
      </div>
      {children}
    </div>
  );
}

/** A phone body around a real phone-width screenshot. */
export function PhoneFrame({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-[2rem] border-[7px] border-ink bg-ink p-0 shadow-frame ${className}`}>
      <div className="overflow-hidden rounded-[1.5rem] bg-white">{children}</div>
    </div>
  );
}

/** A screenshot <img> with its size, lazy unless it is above the fold. */
export function Shot({
  src,
  alt,
  width,
  height,
  eager = false,
  priority = false,
  className = "",
  sizes,
  srcSet,
}: {
  src: string;
  alt: string;
  width: number;
  height: number;
  eager?: boolean;
  /** The largest image of the first screen (the LCP image): fetched first. */
  priority?: boolean;
  className?: string;
  sizes?: string;
  srcSet?: string;
}) {
  return (
    // Static export with unoptimised images (next.config.ts): a plain <img> with its own size and loading hint.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      srcSet={srcSet}
      sizes={sizes}
      alt={alt}
      width={width}
      height={height}
      loading={eager ? "eager" : "lazy"}
      fetchPriority={priority ? "high" : undefined}
      decoding="async"
      className={`block h-auto w-full ${className}`}
    />
  );
}
