"use client";

import { useEffect, useRef, useState } from "react";
import Modal from "@/components/review/Modal";
import type { RtProposal } from "@/lib/runtime";

/** Where the document comes from: a static URL (signed-out sample) or a loader (the user's OneDrive, via Graph). */
export interface ImageSource {
  url?: string;
  load?: () => Promise<Blob>;
}

type Crop = NonNullable<RtProposal["crop"]>;
type Box = [number, number, number, number];

/** Fetch the image only once the card is close to the viewport, and free the blob afterwards. */
function useLazyUrl(source: ImageSource | null) {
  const ref = useRef<HTMLButtonElement>(null);
  const [near, setNear] = useState(false);
  const [blob, setBlob] = useState<{ url: string; type: string } | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setNear(true), { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near || !source?.load || source.url) return;
    let url = "";
    let live = true;
    source
      .load()
      .then((b) => {
        url = URL.createObjectURL(b);
        if (live) setBlob({ url, type: b.type });
        else URL.revokeObjectURL(url);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [near, source]);

  const url = source?.url ?? blob?.url ?? null;
  const isPdf = blob?.type === "application/pdf" || /\.pdf$/i.test(source?.url ?? "");
  return { ref, url: near ? url : null, isPdf, failed, wake: () => setNear(true) };
}

/** The box shown on its own: the image scaled so the box fills the frame. Natural size when zoomed. */
function CropView({ url, box, alt, zoomed }: { url: string; box: Box; alt: string; zoomed: boolean }) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [x0, y0, x1, y1] = box;
  const bw = Math.max(1, x1 - x0), bh = Math.max(1, y1 - y0);
  return (
    <div className="relative overflow-hidden bg-ground" style={{ aspectRatio: `${bw} / ${bh}`, width: zoomed ? bw : "100%", maxWidth: zoomed ? "none" : "100%" }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- a blob: URL from the user's OneDrive, not a static asset */}
      <img
        src={url}
        alt={alt}
        decoding="async"
        onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        className="absolute max-w-none"
        style={
          natural
            ? { width: `${(natural.w / bw) * 100}%`, left: `${(-x0 / bw) * 100}%`, top: `${(-y0 / bh) * 100}%` }
            : { visibility: "hidden" }
        }
      />
    </div>
  );
}

function Pane({ title, note, children, zoomed, onZoom }: { title: string; note: string; children: React.ReactNode; zoomed: boolean; onZoom: () => void }) {
  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <figcaption>
        <p className="text-[15px] font-bold">{title}</p>
        <p className="text-sm text-muted">{note}</p>
      </figcaption>
      <button
        type="button"
        onClick={onZoom}
        aria-pressed={zoomed}
        aria-label={`${title}: ${zoomed ? "zoom out" : "zoom in"}`}
        className={`block max-h-[70dvh] overflow-auto rounded-xl border border-border bg-ground text-left ${zoomed ? "cursor-zoom-out" : "cursor-zoom-in"}`}
      >
        {children}
      </button>
    </figure>
  );
}

export default function ReviewImage({ source, crop, label }: { source: ImageSource | null; crop?: RtProposal["crop"]; label: string }) {
  const { ref, url, isPdf, failed, wake } = useLazyUrl(source);
  const [open, setOpen] = useState(false);
  const [zoom, setZoom] = useState<"original" | "crop" | null>(null);
  const cropped: (Crop & { box: Box }) | null = crop && crop.method !== "none" && crop.box ? (crop as Crop & { box: Box }) : null;

  const frame = "flex h-[150px] w-full shrink-0 items-center justify-center overflow-hidden rounded-xl bg-ground text-sm font-semibold text-muted sm:h-[230px] sm:w-[180px]";
  if (!source || failed)
    return (
      <div className={frame} role="img" aria-label={failed ? "Preview unavailable" : "No image for this proposal"}>
        {failed ? "Preview unavailable" : "No image"}
      </div>
    );

  return (
    <>
      <button
        ref={ref}
        type="button"
        onFocus={wake} // tabbing to an offscreen card loads it too
        onClick={() => {
          wake();
          setOpen(true);
        }}
        aria-label={`Open the document for ${label}${cropped ? " (original and crop side by side)" : ""}`}
        className={`${frame} relative cursor-zoom-in`}
      >
        {!url ? (
          "Loading…"
        ) : isPdf ? (
          "PDF · open"
        ) : (
          // eslint-disable-next-line @next/next/no-img-element -- blob: URLs and static samples; next/image cannot optimise either
          <img src={url} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
        )}
        {cropped && url && (
          <span className="absolute bottom-2 left-2 rounded-full bg-white/90 px-2 py-0.5 text-[12px] font-bold text-teal-dark">Cropped</span>
        )}
      </button>
      {open && (
        <Modal label={`Document: ${label}`} wide onClose={() => { setOpen(false); setZoom(null); }}>
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-lg font-extrabold tracking-tight">{label}</h2>
            <button type="button" onClick={() => { setOpen(false); setZoom(null); }} className="h-11 shrink-0 rounded-xl border border-border px-4 text-[15px] font-bold">
              Close <span className="sr-only">the document</span><kbd className="ml-1 hidden text-[12px] text-muted sm:inline">Esc</kbd>
            </button>
          </div>
          {!url ? (
            <p role="status" className="mt-4 text-[15px] text-muted">Loading the document…</p>
          ) : isPdf ? (
            <iframe src={url} title={`PDF: ${label}`} className="mt-4 h-[75dvh] w-full rounded-xl border border-border" />
          ) : (
            <div className={`mt-4 grid gap-4 ${cropped && !zoom ? "md:grid-cols-2" : ""}`}>
              {zoom !== "crop" && (
                <Pane
                  title="Original"
                  note={cropped ? "The file as it arrived. Duplicate checks use this file." : "Read as it arrived: not cropped."}
                  zoomed={zoom === "original"}
                  onZoom={() => setZoom(zoom === "original" ? null : "original")}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- see above */}
                  <img src={url} alt={`Original document: ${label}`} decoding="async" className={zoom === "original" ? "max-w-none" : "h-auto w-full"} />
                </Pane>
              )}
              {cropped && zoom !== "original" && (
                <Pane
                  title="What was read"
                  note={`${cropped.note || "Cropped"}. The reading and the checks used this part.`}
                  zoomed={zoom === "crop"}
                  onZoom={() => setZoom(zoom === "crop" ? null : "crop")}
                >
                  <CropView url={url} box={cropped.box} alt={`Cropped document: ${label}`} zoomed={zoom === "crop"} />
                </Pane>
              )}
            </div>
          )}
          <p className="mt-3 text-sm text-muted">Click an image to zoom; Esc closes.</p>
        </Modal>
      )}
    </>
  );
}
