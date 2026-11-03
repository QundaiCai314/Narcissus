"use client";
import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { request, errorText } from "@/lib/api";

export function PdfPreview({
  documentId,
  page,
  filename,
  version,
}: {
  documentId: string;
  page: number;
  filename: string;
  version?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [width, setWidth] = useState(400);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [rendered, setRendered] = useState(0);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(100, entry.contentRect.width - 24)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    let loadingTask:
      ReturnType<typeof import("pdfjs-dist").getDocument> | undefined;
    setPdf(null);
    setError("");
    setRendered(0);
    (async () => {
      const lib = await import("pdfjs-dist");
      lib.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.mjs";
      const response = await request(`/documents/${documentId}/file${version ? `?version=${version}` : ""}`, {
        signal: abort.signal,
      });
      const data = new Uint8Array(await response.arrayBuffer());
      if (abort.signal.aborted) return;
      loadingTask = lib.getDocument({
        data,
        cMapUrl: "/pdfjs/cmaps/",
        cMapPacked: true,
        standardFontDataUrl: "/pdfjs/standard_fonts/",
        wasmUrl: "/pdfjs/wasm/",
        useSystemFonts: true,
      });
      const document = await loadingTask.promise;
      if (!abort.signal.aborted) setPdf(document);
    })().catch((e) => {
      if (!abort.signal.aborted) setError(errorText(e));
    });
    return () => {
      abort.abort();
      void loadingTask?.destroy();
    };
  }, [documentId, version, attempt]);

  useEffect(() => {
    if (!pdf || !canvas.current) return;
    let disposed = false;
    let renderTask:
      | ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]>
      | undefined;
    setRendered(0);
    setError("");
    (async () => {
      const current = await pdf.getPage(
        Math.max(1, Math.min(pdf.numPages, page)),
      );
      if (disposed || !canvas.current) return;
      const viewport = current.getViewport({
        scale: width / current.getViewport({ scale: 1 }).width,
      });
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const element = canvas.current;
      element.width = Math.ceil(viewport.width * ratio);
      element.height = Math.ceil(viewport.height * ratio);
      element.style.width = `${viewport.width}px`;
      element.style.height = `${viewport.height}px`;
      renderTask = current.render({
        canvas: element,
        viewport,
        transform: [ratio, 0, 0, ratio, 0, 0],
      });
      await renderTask.promise;
      if (!disposed) setRendered(page);
    })().catch((e) => {
      if (!disposed) setError(errorText(e));
    });
    return () => {
      disposed = true;
      renderTask?.cancel();
    };
  }, [pdf, page, width]);

  return (
    <div ref={container} className="pdf-canvas-scroll">
      {error ? (
        <div className="pdf-notice" role="alert">
          <p>原文暂时无法显示：{error}</p>
          <button className="button" onClick={() => setAttempt((v) => v + 1)}>
            重新加载原文
          </button>
        </div>
      ) : (
        rendered !== page && (
          <p className="pdf-notice" role="status">
            正在加载原文…
          </p>
        )
      )}
      <canvas
        ref={canvas}
        aria-label={`${filename} 第 ${page} 页原文`}
        data-page={rendered || undefined}
        style={{
          visibility: rendered === page && !error ? "visible" : "hidden",
        }}
      />
    </div>
  );
}
