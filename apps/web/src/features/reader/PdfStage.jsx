import { useCallback, useEffect, useRef, useState } from "react";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { API } from "../../shared/api/client.js";
import { cellBands, clampBox, quoteBoxes, textRunBoxes } from "./pdfHighlight.js";
import { PART_COLORS } from "./partColors.js";

const PAD = 3; // the cell fill reaches a little past the digits so none touch the edge

/** Show the PDF's own text only when it is written differently from the value, e.g. "(1.234)" read as -1.234. */
function showRaw(focus) {
  const plain = (text) => String(text ?? "").replace(/[\s.,]/g, "");
  return Boolean(focus.raw && focus.value && plain(focus.raw) !== plain(focus.value));
}

function Thumb({ pdf, number, active, marked, onOpen }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    let cancelled = false;
    pdf.getPage(number).then((page) => {
      if (cancelled || !canvasRef.current) return;
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: 64 / base.width });
      const canvas = canvasRef.current;
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      page.render({ canvasContext: canvas.getContext("2d"), viewport });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [pdf, number]);
  return <button type="button" className={`rd-thumb${active ? " active" : ""}`} onClick={() => onOpen(number)} aria-label={`Trang ${number}`} aria-current={active ? "page" : undefined}>
    <canvas ref={canvasRef} aria-hidden="true" />
    <span>{number}{marked && <i title="Trang có số được nhắc tới trong ghi chú" aria-label="có số được nhắc tới" />}</span>
  </button>;
}

export function PdfStage({ report, focus, onClearFocus, processing, markedPages, evidences = [] }) {
  const scrollRef = useRef(null);
  const canvasRef = useRef(null);
  const renderRef = useRef(null);
  const autoFit = useRef(true);
  const [pdf, setPdf] = useState(null);
  const [page, setPage] = useState(1);
  const [scale, setScale] = useState(null);
  const [size, setSize] = useState(null);
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");

  // Load the PDF itself; it shows even while the text is still being read.
  useEffect(() => {
    let disposed = false;
    let task;
    setPdf(null); setPage(1); setError(""); setItems([]); setSize(null); setScale(null); autoFit.current = true;
    scrollRef.current?.scrollTo({ top: 0, left: 0 });
    if (!report) return undefined;
    const url = new URL(report.file_url || `/api/v1/sessions/${report.sessionId}/documents/${report.id}/file`, API).toString();
    import("pdfjs-dist").then((pdfjs) => {
      if (disposed) return null;
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      task = pdfjs.getDocument({ url, withCredentials: true });
      return task.promise;
    }).then((loaded) => { if (loaded && !disposed) setPdf(loaded); })
      .catch((reason) => { if (!disposed) setError(reason?.message || "Không mở được PDF"); });
    return () => { disposed = true; task?.destroy(); };
  }, [report?.id, report?.file_url]);

  const fit = useCallback(async () => {
    if (!pdf || !scrollRef.current) return;
    const first = await pdf.getPage(page);
    const base = first.getViewport({ scale: 1 });
    const next = Math.max(0.4, Math.min(1.6, (scrollRef.current.clientWidth - 48) / base.width));
    setScale((current) => Math.abs(current - next) < 0.01 ? current : next);
  }, [pdf, page]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!pdf || !node) return undefined;
    const refit = () => { if (autoFit.current) fit(); };
    refit();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(refit);
    observer.observe(node);
    return () => observer.disconnect();
  }, [pdf, fit]);

  useEffect(() => {
    // Draw only once the page has its fitted size, so the zoom never jumps after loading.
    if (!pdf || !canvasRef.current || !scale) return undefined;
    let cancelled = false;
    pdf.getPage(page).then((pdfPage) => {
      if (cancelled) return;
      const viewport = pdfPage.getViewport({ scale });
      const ratio = window.devicePixelRatio || 1;
      const canvas = canvasRef.current;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      setSize({ width: viewport.width, height: viewport.height, transform: viewport.transform, scale });
      pdfPage.getTextContent().then((content) => { if (!cancelled) setItems(content.items.filter((item) => item.str?.trim())); }).catch(() => setItems([]));
      renderRef.current?.cancel();
      renderRef.current = pdfPage.render({ canvasContext: canvas.getContext("2d"), viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] });
      renderRef.current.promise.catch(() => {});
    }).catch((reason) => { if (!cancelled) setError(reason?.message || "Không vẽ được trang"); });
    return () => { cancelled = true; renderRef.current?.cancel(); };
  }, [pdf, page, scale]);

  // Go to the page of whatever was tapped, and zoom in when its digits would
  // be smaller than about 14 px, so the number in the ring can be read.
  useEffect(() => {
    if (!pdf || !focus?.page) return;
    setPage(Math.min(Math.max(1, focus.page), pdf.numPages));
    const box = (focus.boxes ?? []).map(clampBox).find(Boolean);
    if (!box || !size) return;
    const pageHeight = size.height / size.scale;
    const textPx = (box[3] - box[1]) * pageHeight * size.scale;
    if (textPx >= 13) return;
    autoFit.current = false;
    setScale(Math.min(3, Math.max(size.scale * (15 / Math.max(textPx, 4)), window.matchMedia?.("(max-width: 700px)").matches ? 1.4 : 0)));
  }, [focus?.nonce, pdf]);

  // Keep the middle of the view in place when zooming with the buttons.
  const anchor = useRef(null);
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !anchor.current || !size) return;
    const { cx, cy } = anchor.current;
    anchor.current = null;
    node.scrollTo({ left: Math.max(0, cx * node.scrollWidth - node.clientWidth / 2), top: Math.max(0, cy * node.scrollHeight - node.clientHeight / 2) });
  }, [size?.width]);
  const goToPage = (next) => {
    setPage(next);
    scrollRef.current?.scrollTo({ top: 0 });
  };

  const onFocusPage = focus?.page === page;
  const boxes = onFocusPage && size ? ((focus.boxes ?? []).map(clampBox).filter(Boolean).length ? (focus.boxes ?? []).map(clampBox).filter(Boolean) : quoteBoxes(items, size, focus.quote)) : [];
  const toRect = ([x0, y0, x1, y1], pad = PAD) => ({ x: x0 * size.width - pad, y: y0 * size.height - pad, w: (x1 - x0) * size.width + pad * 2, h: (y1 - y0) * size.height + pad * 2 });
  const rects = size ? boxes.map((box) => toRect(box)) : [];
  // Row and column through a single table cell; a calculation colours its inputs instead.
  const multi = rects.length > 1 && focus?.parts?.length === rects.length;
  const bands = size && rects.length === 1 && focus?.key ? cellBands(evidences, focus.key, page, textRunBoxes(items, size)) : null;

  // Bring the first ring into view.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !rects.length) return;
    // Move only as far as needed, so row and column names next to the cell stay in view.
    const margin = 48;
    const x0 = Math.min(...rects.map((r) => r.x)) + 24;
    const x1 = Math.max(...rects.map((r) => r.x + r.w)) + 24;
    const y0 = Math.min(...rects.map((r) => r.y)) + 24;
    const y1 = Math.max(...rects.map((r) => r.y + r.h)) + 24;
    let left = node.scrollLeft;
    if (x1 > left + node.clientWidth - margin) left = x1 - node.clientWidth + margin;
    if (x0 < left + margin) left = x0 - margin;
    let top = node.scrollTop;
    if (y0 < top + margin || y1 > top + node.clientHeight - margin) top = y0 - node.clientHeight / 3;
    node.scrollTo({ top: Math.max(0, top), left: Math.max(0, left), behavior: "smooth" });
  }, [focus?.nonce, size?.width, rects.length]);

  const zoom = (step) => {
    const node = scrollRef.current;
    if (node && node.scrollWidth) anchor.current = { cx: (node.scrollLeft + node.clientWidth / 2) / node.scrollWidth, cy: (node.scrollTop + node.clientHeight / 2) / node.scrollHeight };
    autoFit.current = false;
    setScale((value) => Math.max(0.4, Math.min(3, (value ?? 1) + step)));
  };
  const numPages = pdf?.numPages ?? report?.page_count ?? 0;

  useEffect(() => {
    const onKey = (event) => {
      if (event.target.closest?.("input, textarea, [contenteditable]")) return;
      // A panel, dialog, menu or tour on top handles its own keys first.
      if (document.querySelector(".rd-panel, .rd-modal-back, .rd-tour, .rd-popover")) return;
      if (event.key === "ArrowRight" && pdf && page < pdf.numPages) goToPage(page + 1);
      if (event.key === "ArrowLeft" && page > 1) goToPage(page - 1);
      if (event.key === "Escape") onClearFocus?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pdf, page, onClearFocus]);


  return <section className="rd-stage" aria-label="Trang báo cáo">
    {pdf && pdf.numPages > 1 && <nav className="rd-rail" aria-label="Các trang">
      {Array.from({ length: pdf.numPages }, (_, index) => <Thumb key={index} pdf={pdf} number={index + 1} active={page === index + 1} marked={markedPages?.has(index + 1)} onOpen={goToPage} />)}
    </nav>}
    {focus?.page && <div key={focus.nonce} className={`rd-focusbar${focus.unsure ? " unsure" : ""}`} role="status">
      <button type="button" className="rd-focus-close" onClick={onClearFocus} aria-label="Bỏ đánh dấu">×</button>
      {focus.parts?.length > 1
        ? <p className="rd-parts">{focus.value && <b>{focus.value}</b>}<small>tính từ</small>{focus.parts.map((part, i) => <span key={i} className="rd-part" style={{ "--part": PART_COLORS[i % PART_COLORS.length] }}><i aria-hidden="true" />{part.value}{part.label && <em>{part.label}</em>}</span>)}<small>trang {focus.page}</small></p>
        : <p>{focus.value && <b>{focus.value}</b>}<span>{focus.label || "Vị trí trong báo cáo"} · trang {focus.page}{showRaw(focus) && <> · PDF ghi <q>{focus.raw}</q></>}{focus.unsure ? " · mình chưa chắc số này, bạn so với trang giúp nhé" : ""}</span></p>}
      {onFocusPage && !rects.length && size && <small>Không có vị trí chính xác cho mục này</small>}
    </div>}
    <div className="rd-scroll" ref={scrollRef}>
      {!pdf && !error && <div className="rd-page-skeleton" aria-hidden="true" />}
      {error && <p className="rd-stage-error" role="alert">Không mở được PDF này. {error}</p>}
      <div className="rd-page" style={size ? { width: size.width, height: size.height } : undefined}>
        <canvas ref={canvasRef} />
        {processing && pdf && <div className="rd-scan" aria-hidden="true"><span /><em><i className="rd-spinner small" />Đang đọc trang này…</em></div>}
        {rects.length > 0 && <svg className={`rd-spotlight${focus?.unsure ? " unsure" : ""}`} width={size.width} height={size.height} onClick={onClearFocus} role="presentation">
          {bands && <g className="rd-bands">{[bands.row, bands.column].map((band, i) => { const r = toRect(band, 2); return <rect key={i} x={r.x} y={r.y} width={r.w} height={r.h} rx="3" />; })}</g>}
          {rects.map((r, i) => <rect key={`${focus.nonce}-${i}`} className="rd-cell" x={r.x} y={r.y} width={r.w} height={r.h} rx="3" style={multi ? { "--part": PART_COLORS[i % PART_COLORS.length] } : undefined} data-part={multi ? i : undefined} />)}
        </svg>}
      </div>
    </div>
    <div className="rd-stage-tools" role="toolbar" aria-label="Điều khiển trang">
      <button type="button" onClick={() => goToPage(Math.max(1, page - 1))} disabled={page <= 1} aria-label="Trang trước">‹</button>
      <span><span className="rd-page-word">Trang </span>{page} / {numPages || "…"}</span>
      <button type="button" onClick={() => pdf && goToPage(Math.min(pdf.numPages, page + 1))} disabled={!pdf || page >= pdf.numPages} aria-label="Trang sau">›</button>
      <i aria-hidden="true" />
      <button type="button" onClick={() => zoom(-0.15)} aria-label="Thu nhỏ">−</button>
      <span className="rd-zoom" aria-live="polite">{scale ? `${Math.round(scale * 100)}%` : ""}</span>
      <button type="button" onClick={() => zoom(0.15)} aria-label="Phóng to">+</button>
      <button type="button" onClick={() => { autoFit.current = true; fit(); }} className="rd-fit">Vừa khung</button>
    </div>
  </section>;
}
