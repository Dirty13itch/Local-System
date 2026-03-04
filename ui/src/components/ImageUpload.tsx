"use client";

import { useCallback, useState, useRef } from "react";

interface Props {
  onUpload: (file: File) => Promise<void> | void;
  accept?: string;
  multiple?: boolean;
  label?: string;
  preview?: string | null;
  className?: string;
}

export function ImageUpload({
  onUpload,
  accept = "image/*",
  multiple = false,
  label = "Drop image here or click to browse",
  preview,
  className = "",
}: Props) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      setUploading(true);
      try {
        if (multiple) {
          for (let i = 0; i < files.length; i++) {
            await onUpload(files[i]);
          }
        } else {
          await onUpload(files[0]);
        }
      } finally {
        setUploading(false);
      }
    },
    [onUpload, multiple],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  return (
    <div
      className={`
        relative rounded-lg border-2 border-dashed transition-colors cursor-pointer
        flex flex-col items-center justify-center gap-2 p-6 min-h-[160px]
        ${dragging ? "border-[var(--accent)] bg-[var(--accent)]/5" : "border-[var(--border)] hover:border-[var(--text-secondary)]"}
        ${className}
      `}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      {preview ? (
        <img
          src={preview}
          alt="Preview"
          className="max-h-[200px] rounded object-contain"
        />
      ) : (
        <>
          <svg className="w-8 h-8 text-[var(--text-secondary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
            />
          </svg>
          <p className="text-sm text-[var(--text-secondary)]">{uploading ? "Uploading..." : label}</p>
        </>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {uploading && (
        <div className="absolute inset-0 bg-[var(--bg-primary)]/60 rounded-lg flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
        </div>
      )}
    </div>
  );
}
