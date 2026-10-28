/** The Accnomos mark (the hexagon with a tick), as in the app shell, in any colour pair. */
export function LogoMark({ className = "bg-teal", stroke = "#F4F3EE" }: { className?: string; stroke?: string }) {
  return (
    <span aria-hidden="true" className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${className}`}>
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        <path d="M10 2.5 16.5 6v8L10 17.5 3.5 14V6L10 2.5Z" stroke={stroke} strokeWidth="1.8" strokeLinejoin="round" />
        <path
          d="M7 10.2l2.1 2.1L13.2 8"
          stroke={stroke}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
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
