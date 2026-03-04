"use client";

import { useState, useCallback } from "react";

interface GalleryImage {
  src: string;
  alt?: string;
  prompt?: string;
  timestamp?: string;
}

interface Props {
  images: GalleryImage[];
  columns?: number;
  className?: string;
}

export function ImageGallery({ images, columns = 3, className = "" }: Props) {
  const [lightbox, setLightbox] = useState<number | null>(null);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (lightbox === null) return;
      if (e.key === "Escape") setLightbox(null);
      if (e.key === "ArrowRight") setLightbox((i) => (i !== null && i < images.length - 1 ? i + 1 : i));
      if (e.key === "ArrowLeft") setLightbox((i) => (i !== null && i > 0 ? i - 1 : i));
    },
    [lightbox, images.length],
  );

  if (images.length === 0) {
    return (
      <div className={`text-center py-8 text-[var(--text-secondary)] ${className}`}>
        <p className="text-sm">No images yet. Generate something!</p>
      </div>
    );
  }

  return (
    <>
      <div
        className={`grid gap-3 ${className}`}
        style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
      >
        {images.map((img, i) => (
          <button
            key={i}
            onClick={() => setLightbox(i)}
            className="relative aspect-square rounded-lg overflow-hidden border border-[var(--border)] bg-[var(--bg-tertiary)] hover:border-[var(--accent)] transition-colors group"
          >
            <img
              src={img.src}
              alt={img.alt || `Generated ${i + 1}`}
              className="w-full h-full object-cover"
              loading="lazy"
            />
            {img.prompt && (
              <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                <p className="text-xs text-white truncate">{img.prompt}</p>
              </div>
            )}
          </button>
        ))}
      </div>

      {/* Lightbox */}
      {lightbox !== null && (
        <div
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
          onClick={() => setLightbox(null)}
          onKeyDown={handleKeyDown}
          tabIndex={0}
        >
          <button
            onClick={() => setLightbox(null)}
            className="absolute top-4 right-4 text-white/60 hover:text-white text-2xl"
          >
            ✕
          </button>

          {lightbox > 0 && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setLightbox(lightbox - 1);
              }}
              className="absolute left-4 top-1/2 -translate-y-1/2 text-white/60 hover:text-white text-3xl"
            >
              ‹
            </button>
          )}

          {lightbox < images.length - 1 && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setLightbox(lightbox + 1);
              }}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-white/60 hover:text-white text-3xl"
            >
              ›
            </button>
          )}

          <div className="max-w-[90vw] max-h-[90vh] flex flex-col items-center gap-4" onClick={(e) => e.stopPropagation()}>
            <img
              src={images[lightbox].src}
              alt={images[lightbox].alt || ""}
              className="max-w-full max-h-[80vh] object-contain rounded-lg"
            />
            {images[lightbox].prompt && (
              <p className="text-sm text-white/70 max-w-2xl text-center">{images[lightbox].prompt}</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
