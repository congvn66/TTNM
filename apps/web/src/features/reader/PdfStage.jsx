import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { API } from "../../shared/api/client.js";
import { cellBands, clampBox, quoteBoxes, textRunBoxes } from "./pdfHighlight.js";
import { FormulaLine, InputTag, partColor, partInk, peekProps } from "./Calc.jsx";
import { readableFormula } from "./formulaView.js";
import { cellName, cellNumber, cellRange, cellUnsure, isNumberCell, neighbourCell, pageProse, pageTables, summarizeSelection } from "./cells.js";
import { formatNumber as formatValue, scrollBehavior, valueWithUnit } from "./format.js";

const SHOW_READ_KEY = "sourcelens-show-read-v1";
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

const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

/**
 * Every extracted table cell as a real control over the page: an invisible
 * ARIA grid (one Tab stop, arrows inside), tap to open its card, drag or
 * Shift+click to select. The PDF itself stays an image underneath.
 */
function CellLayer({ tables, size, page, openKey, selection, selectMode, picking, pickHover, onPickHover, onPickChoose, onOpen, onSelect, onAnnounce, onBlank, onDenseTap }) {
  const lastPointer = useRef("mouse");
  // One Tab stop per table: the cell last visited in it, else its first cell.
  const [roving, setRovingMap] = useState({});
  const anchor = useRef(null);
  const drag = useRef(null);
  const suppress = useRef(false);
  const [band, setBand] = useState(null);
    // Extraction boxes hug the digits; a few pixels more make them easy to hit.
  // On touch a cell is at least 24 px tall (WCAG 2.5.8), but never reaches into the next row of its table.
  // pitch is the distance to the nearest row: below 24 px no box can be both big and separate.
  const pitch = useRef(new Map());
  const room = useMemo(() => {
    const out = new Map();
    pitch.current = new Map();
    if (typeof window === "undefined" || !window.matchMedia?.("(pointer: coarse)").matches) return out;
    for (const table of tables) {
      const middles = table.rows.map((row) => row.reduce((acc, cell) => { const b = clampBox(cell.bbox); return acc + (b[1] + b[3]) / 2; }, 0) / row.length * size.height);
      table.rows.forEach((row, i) => {
        const gap = Math.min(...[middles[i - 1], middles[i + 1]].filter((y) => y != null).map((y) => Math.abs(y - middles[i])), Infinity);
        row.forEach((cell) => { out.set(cell.evidence_key, Math.min(24, Number.isFinite(gap) ? gap - 2 : 24)); pitch.current.set(cell.evidence_key, gap); });
      });
    }
    return out;
  }, [tables, size]);
  const box = (cell) => {
    const [x0, y0, x1, y1] = clampBox(cell.bbox);
    const height = Math.max((y1 - y0) * size.height + 6, room.get(cell.evidence_key) ?? 0);
    const middle = (y0 + y1) / 2 * size.height;
    return { left: x0 * size.width - 4, top: middle - height / 2, width: (x1 - x0) * size.width + 8, height };
  };
  const all = tables.flatMap((table) => table.cells);
  const tableOf = (key) => tables.find((table) => table.cells.some((cell) => cell.evidence_key === key));
  const setRoving = (key) => { const table = tableOf(key); if (table) setRovingMap((map) => (map[table.key] === key ? map : { ...map, [table.key]: key })); };
  const tabKeyOf = (table) => (table.cells.some((cell) => cell.evidence_key === roving[table.key]) ? roving[table.key] : table.rows[0]?.[0]?.evidence_key);
  const announce = (keys) => {
    const summary = summarizeSelection(all.filter((cell) => keys.includes(cell.evidence_key)));
    if (summary) onAnnounce(`Đã chọn ${summary.count} ô, tổng ${formatValue(String(Math.round(summary.sum * 100) / 100))}.${summary.caveats.length ? ` Lưu ý: ${summary.caveats.join(", ")}.` : ""}`);
  };
  const select = (keys) => { onSelect(keys); announce(keys); };
  const focusCell = (key) => { setRoving(key); window.requestAnimationFrame(() => document.querySelector(`[data-cell="${CSS.escape(key)}"]`)?.focus()); };

  const onPointerDown = (event) => {
    lastPointer.current = event.pointerType || "mouse";
    // Choosing a cell for a calculation is a tap, never a drag.
    if (picking || event.button !== 0 || (event.pointerType === "touch" && !selectMode)) return;
    const rect = event.currentTarget.getBoundingClientRect();
    drag.current = { x0: event.clientX - rect.left, y0: event.clientY - rect.top, rect, moved: false, id: event.pointerId, start: event.target.closest?.("[data-cell]")?.dataset.cell ?? null };
  };
  useEffect(() => {
    const move = (event) => {
      const state = drag.current;
      if (!state || event.pointerId !== state.id) return;
      const x = event.clientX - state.rect.left; const y = event.clientY - state.rect.top;
      if (!state.moved && Math.hypot(x - state.x0, y - state.y0) < 6) return;
      state.moved = true;
      const area = { left: Math.min(x, state.x0), top: Math.min(y, state.y0), width: Math.abs(x - state.x0), height: Math.abs(y - state.y0) };
      setBand(area);
      // As in a spreadsheet: the start cell and the cell under the pointer span the selection.
      const here = document.elementFromPoint(event.clientX, event.clientY)?.closest?.("[data-cell]")?.dataset.cell;
      let keys;
      if (state.start) {
        if (!here || tableOf(here) !== tableOf(state.start)) return;
        keys = cellRange(tableOf(here), state.start, here);
      } else {
        // A drag that starts on blank page takes the cells whose middle is inside the box.
        keys = all.filter((cell) => { const b = box(cell); const cx = b.left + b.width / 2; const cy = b.top + b.height / 2; return cx >= area.left && cx <= area.left + area.width && cy >= area.top && cy <= area.top + area.height; }).map((cell) => cell.evidence_key);
      }
      // Kept on the drag itself: a fast release can come before React has rendered the last move.
      state.keys = keys;
      onSelect(keys);
    };
    const up = (event) => {
      const state = drag.current;
      if (!state || event.pointerId !== state.id) return;
      drag.current = null;
      // The click that ends a drag must not open a card; clear the flag once that click has passed.
      if (state.moved) { suppress.current = true; window.setTimeout(() => { suppress.current = false; }, 0); setBand(null); announce(state.keys ?? []); }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    // The browser took the touch over (a scroll or a system gesture): keep what was selected so far.
    window.addEventListener("pointercancel", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up); };
  });

  const onCellClick = (event, key) => {
    if (suppress.current) { suppress.current = false; return; }
    // A finger cannot pick one of rows this close: the first tap zooms in, the next one acts on the cell.
    if (lastPointer.current === "touch" && (pitch.current.get(key) ?? Infinity) < 24) { onDenseTap?.(key, pitch.current.get(key)); return; }
    if (picking) {
      // On touch the first tap shows the new result, a second tap on the same cell uses it.
      if (lastPointer.current === "touch" && pickHover !== key) onPickHover(key);
      else onPickChoose(key);
      return;
    }
    setRoving(key);
    if (event.shiftKey && anchor.current && tableOf(anchor.current) === tableOf(key)) { select(cellRange(tableOf(key), anchor.current, key)); return; }
    anchor.current = key;
    onOpen(key);
  };
  const onKeyDown = (event, key) => {
    const move = ARROWS[event.key];
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onCellClick(event, key); return; }
    if (!move) return;
    event.preventDefault();
    const next = neighbourCell(tableOf(key), key, move[0], move[1]);
    if (!next) return;
    if (event.shiftKey) { if (!anchor.current) anchor.current = key; select(cellRange(tableOf(key), anchor.current, next.evidence_key)); }
    else anchor.current = next.evidence_key;
    focusCell(next.evidence_key);
  };

  return <div className={`rd-cells${selectMode ? " select-mode" : ""}${picking ? " picking" : ""}`} onPointerDown={onPointerDown} onClick={(event) => { if (event.target === event.currentTarget && !suppress.current && !picking) onBlank?.(); suppress.current = false; }}>
    <p id="rd-grid-help" className="rd-sr">Mũi tên để đi giữa các ô, Shift và mũi tên để chọn nhiều ô, Enter để xem ô.</p>
    {tables.map((table, index) => <div key={table.key} role="grid" aria-multiselectable="true" aria-label={`Bảng ${index + 1}, trang ${page}`} aria-describedby="rd-grid-help">
      {table.rows.map((row, rowIndex) => <div key={rowIndex} role="row" className="rd-cellrow">
        {row.map((cell) => {
          const value = cellNumber(cell);
          return <div key={cell.evidence_key} role="gridcell" data-cell={cell.evidence_key} tabIndex={cell.evidence_key === tabKeyOf(table) ? 0 : -1}
            aria-selected={selection.includes(cell.evidence_key)} aria-expanded={openKey === cell.evidence_key ? true : undefined}
            aria-label={`${cellName(cell)}: ${value == null ? "không có số" : formatValue(cell.current_numeric_value)}${cellUnsure(cell) ? ", chưa chắc" : ""}`}
            className={`rd-hit${openKey === cell.evidence_key ? " open" : ""}`} style={box(cell)}
            onClick={(event) => onCellClick(event, cell.evidence_key)} onKeyDown={(event) => onKeyDown(event, cell.evidence_key)} onFocus={(event) => {
              setRoving(cell.evidence_key);
              // Keyboard focus previews; a tap also focuses, and its own first-tap preview must decide.
              if (picking && event.currentTarget.matches(":focus-visible")) onPickHover(cell.evidence_key, true);
            }}
            onPointerEnter={(event) => { if (picking && event.pointerType !== "touch") onPickHover(cell.evidence_key); }} />;
        })}
      </div>)}
    </div>)}
    {band && <div className="rd-band" style={band} aria-hidden="true" />}
  </div>;
}

/**
 * The numbers in the page's running text as buttons over their digits: one Tab
 * stop, arrow keys go to the next or previous number in reading order, Enter
 * or a tap opens the number's card. Text numbers are not selected or summed.
 */
function ProseLayer({ cells, size, page, openKey, picking, pickHover, onPickHover, onPickChoose, onOpen }) {
  const lastPointer = useRef("mouse");
  const [roving, setRoving] = useState(null);
  const tabKey = cells.some((cell) => cell.evidence_key === roving) ? roving : cells[0]?.evidence_key;
  // On touch a number is at least 24 px tall (WCAG 2.5.8), but never reaches a number on the line above or below.
  const touch = typeof window !== "undefined" && Boolean(window.matchMedia?.("(pointer: coarse)").matches);
  const room = useMemo(() => {
    const out = new Map();
    if (!touch) return out;
    const boxes = cells.map((cell) => clampBox(cell.bbox));
    boxes.forEach(([x0, y0, x1, y1], i) => {
      const middle = (y0 + y1) / 2 * size.height;
      const gaps = boxes.filter(([a0, , a1], j) => j !== i && a0 * size.width < x1 * size.width + 24 && a1 * size.width > x0 * size.width - 24)
        .map(([, b0, , b1]) => Math.abs((b0 + b1) / 2 * size.height - middle)).filter((gap) => gap > 1);
      out.set(cells[i].evidence_key, Math.min(24, ...gaps.map((gap) => gap - 2)));
    });
    return out;
  }, [cells, size, touch]);
  const box = (cell) => {
    const [x0, y0, x1, y1] = clampBox(cell.bbox);
    const height = Math.max((y1 - y0) * size.height + 6, room.get(cell.evidence_key) ?? 0);
    const width = Math.max((x1 - x0) * size.width + 8, touch ? 24 : 0);
    return { left: (x0 + x1) / 2 * size.width - width / 2, top: (y0 + y1) / 2 * size.height - height / 2, width, height };
  };
  const focusCell = (key) => { setRoving(key); window.requestAnimationFrame(() => document.querySelector(`[data-cell="${CSS.escape(key)}"]`)?.focus()); };
  const act = (key) => {
    setRoving(key);
    if (!picking) { onOpen(key); return; }
    // As in a table: on touch the first tap shows the new result, a second tap uses it.
    if (lastPointer.current === "touch" && pickHover !== key) onPickHover(key);
    else onPickChoose(key);
  };
  const onKeyDown = (event, index) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); act(cells[index].evidence_key); return; }
    const next = event.key === "Home" ? 0 : event.key === "End" ? cells.length - 1 : step ? index + step : null;
    if (next == null) return;
    event.preventDefault();
    if (cells[next]) focusCell(cells[next].evidence_key);
  };
  return <div className={`rd-prose${picking ? " picking" : ""}`} role="group" aria-label={`Số trong đoạn văn, trang ${page}`} aria-describedby="rd-prose-help">
    <p id="rd-prose-help" className="rd-sr">Mũi tên để đi giữa các số, Enter để xem hoặc sửa số.</p>
    {cells.map((cell, index) => <button key={cell.evidence_key} type="button" data-cell={cell.evidence_key} tabIndex={cell.evidence_key === tabKey ? 0 : -1}
      aria-expanded={openKey === cell.evidence_key ? true : undefined}
      aria-label={`${cellName(cell)}: ${cell.current_numeric_value == null ? cell.raw_text : valueWithUnit(cell)}${cellUnsure(cell) ? ", chưa chắc" : ""}`}
      className={`rd-hit${openKey === cell.evidence_key ? " open" : ""}`} style={box(cell)}
      onPointerDown={(event) => { lastPointer.current = event.pointerType || "mouse"; }}
      onClick={() => act(cell.evidence_key)} onKeyDown={(event) => onKeyDown(event, index)}
      onFocus={(event) => { setRoving(cell.evidence_key); if (picking && event.currentTarget.matches(":focus-visible")) onPickHover(cell.evidence_key, true); }}
      onPointerEnter={(event) => { if (picking && event.pointerType !== "touch") onPickHover(cell.evidence_key); }} />)}
  </div>;
}

export function PdfStage({ report, focus, onClearFocus, processing, markedPages, evidences = [], openKey = null, onOpenCell, onCloseCard, selection = [], onSelect, renderCard, checks = [], onDismissCheck, onAskSelection, askingSelection = false, onChartSelection = null, peekKey = null, onPeek, pick = null, onPickHover, onPickChoose, onPickCancel }) {
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
  const [live, setLive] = useState("");
  // Clear first, so the same sentence twice is still read out.
  const announce = useCallback((text) => { setLive(""); window.requestAnimationFrame(() => setLive(text)); }, []);
  // On touch, a drag scrolls the page; this switch makes a drag select cells instead.
  const [selectMode, setSelectMode] = useState(false);
  const [narrow, setNarrow] = useState(false);
  // "Số đã đọc": shade every number the app read, so a number left unshaded is one it missed.
  const [showRead, setShowRead] = useState(() => { try { return localStorage.getItem(SHOW_READ_KEY) === "yes"; } catch { return false; } });
  const toggleRead = () => {
    const next = !showRead;
    try { localStorage.setItem(SHOW_READ_KEY, next ? "yes" : "no"); } catch { /* private mode */ }
    setShowRead(next);
    // The meaning of the shading is said out loud too: a tooltip never reaches touch or keyboard users.
    if (next) announce(`Đã tô ${evidences.filter((cell) => cell.page_number === page && cell.current_numeric_value != null && clampBox(cell.bbox)).length} số mình đọc được ở trang này. Số không được tô là số mình chưa đọc.`);
  };
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => setNarrow(node.clientWidth < 640));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

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
  // After a zoom the open card may sit past the edge of the view; bring it back in.
  useEffect(() => {
    if (!openKey || narrow) return undefined;
    const frame = window.requestAnimationFrame(() => scrollRef.current?.querySelector(".rd-cellcard-anchor")?.scrollIntoView({ block: "nearest", inline: "nearest" }));
    return () => window.cancelAnimationFrame(frame);
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

  const tables = useMemo(() => (size ? pageTables(evidences, page) : []), [evidences, page, size]);
  const prose = useMemo(() => (size ? pageProse(evidences, page) : []), [evidences, page, size]);
  const byKey = useMemo(() => new Map(evidences.map((cell) => [cell.evidence_key, cell])), [evidences]);
  const picked = selection.map((key) => byKey.get(key)).filter(Boolean);
  const summary = summarizeSelection(picked);
  const openCell = openKey ? byKey.get(openKey) : null;
  const cardHere = Boolean(openCell && size && openCell.page_number === page && clampBox(openCell.bbox));
  const pxBox = (cell, pad = 0) => toRect(clampBox(cell.bbox), pad);
  // The card hangs below the whole row, never over the row name or the column header.
  const cardPlace = (() => {
    if (!cardHere || narrow) return null;
    // A number in running text has no row: the card hangs below its own line.
    const row = openCell.table_locator
      ? tables.flatMap((table) => table.cells).filter((cell) => cell.table_locator?.table_region_key === openCell.table_locator.table_region_key && cell.table_locator?.row_index === openCell.table_locator.row_index)
      : [openCell];
    const bottom = Math.max(...row.map((cell) => pxBox(cell).y + pxBox(cell).h));
    const own = pxBox(openCell);
    const left = Math.max(8, Math.min(own.x + own.w / 2 - 40, size.width - 340));
    return { left, top: bottom + 10, notch: Math.max(12, Math.min(own.x + own.w / 2 - left - 6, 300)) };
  })();
  const pageUnsure = size ? evidences.filter((cell) => cell.page_number === page && clampBox(cell.bbox) && cell.table_locator && isNumberCell(cell) && cellUnsure(cell)) : [];
  const pageRead = size && showRead ? evidences.filter((cell) => cell.page_number === page && cell.current_numeric_value != null && clampBox(cell.bbox)) : [];
  const formulaShown = Boolean(focus?.formula && readableFormula(focus.formula.expression, focus.result));
  const pickCells = pick ? (pick.candidates ?? []).map((key) => byKey.get(key)).filter((cell) => cell && cell.page_number === page && clampBox(cell.bbox)) : [];
  // One outlined cell: the one a pick would use, else the input under the pointer or keyboard focus.
  const outline = [pick?.preview?.key, peekKey].map((key) => key && byKey.get(key)).find((cell) => cell && cell.page_number === page && clampBox(cell.bbox)) ?? null;
  const focusProblem = focus?.key ? checks.find((check) => !check.ok && check.chip.key === focus.key) : null;
  const pageProblems = size ? checks.filter((check) => !check.ok).map((check) => byKey.get(check.keys?.[0])).filter((cell) => cell && cell.page_number === page && clampBox(cell.bbox)) : [];
  const closeCard = useCallback(() => { const key = openKey; onCloseCard?.({ byUser: true }); if (key) window.requestAnimationFrame(() => document.querySelector(`[data-cell="${CSS.escape(key)}"]`)?.focus({ preventScroll: true })); }, [openKey, onCloseCard]);

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
    top = Math.max(0, top); left = Math.max(0, left);
    // No call when nothing moves: a no-op smooth scroll would cancel the card's own scroll into view.
    if (Math.abs(top - node.scrollTop) > 1 || Math.abs(left - node.scrollLeft) > 1) node.scrollTo({ top, left, behavior: scrollBehavior() });
  }, [focus?.nonce, size?.width, rects.length]);

  // Screen readers hear the choice once when it starts, and a preview only when the keyboard asked for it:
  // reading every mouse-over aloud would bury everything else.
  const pickByKeys = useRef(false);
  useEffect(() => {
    if (pick?.key) announce(`Chọn ô thay cho số ${pick.index + 1}, ${pick.value}. Mũi tên để xem kết quả mới, Enter để dùng ô, Esc để huỷ.`);
  }, [pick?.key]);
  useEffect(() => {
    const text = pick?.preview?.text;
    if (pickByKeys.current && text && !text.includes("…")) announce(`${pick.preview.warning ? "Có thể không có nghĩa. " : ""}${text}`);
  }, [pick?.preview?.text]);

  // Choosing starts at the cell being replaced, so arrow keys move from there at once.
  useEffect(() => {
    if (!pick?.key) return undefined;
    const frame = window.requestAnimationFrame(() => document.querySelector(`[data-cell="${CSS.escape(pick.key)}"]`)?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(frame);
  }, [pick?.key, page]);

  // A card or selection from another page is closed when the page changes.
  useEffect(() => {
    if (openCell && openCell.page_number !== page) onCloseCard?.();
    if (picked.some((cell) => cell.page_number !== page)) onSelect?.([]);
  }, [page]);

  // On a phone the sheet covers the lower page: lift the tapped cell above it.
  useEffect(() => {
    if (!cardHere || !narrow) return undefined;
    const node = scrollRef.current;
    const frame = window.requestAnimationFrame(() => {
      const stage = node?.closest(".rd-stage");
      const sheet = stage?.querySelector(".rd-cellsheet");
      const hit = node?.querySelector(`[data-cell="${CSS.escape(openKey)}"]`);
      if (!sheet || !hit) return;
      // Room below the page so even the last row can scroll above the sheet.
      node.style.paddingBottom = `${sheet.offsetHeight}px`;
      stage.scrollIntoView({ block: "nearest" });
      const over = hit.getBoundingClientRect().bottom + 12 - sheet.getBoundingClientRect().top;
      const under = node.getBoundingClientRect().top + 8 - hit.getBoundingClientRect().top;
      if (over > 0) node.scrollBy({ top: over });
      else if (under > 0) node.scrollBy({ top: -under });
    });
    return () => { window.cancelAnimationFrame(frame); if (node) node.style.paddingBottom = ""; };
  }, [openKey, cardHere, narrow]);

  const zoom = (step) => {
    const node = scrollRef.current;
    if (node && node.scrollWidth) anchor.current = { cx: (node.scrollLeft + node.clientWidth / 2) / node.scrollWidth, cy: (node.scrollTop + node.clientHeight / 2) / node.scrollHeight };
    autoFit.current = false;
    setScale((value) => Math.max(0.4, Math.min(3, (value ?? 1) + step)));
  };
  // Zoom so rows are about 32 px apart, keeping the tapped cell in the middle of the view.
  const zoomToCell = (key, rowPitch) => {
    const box = clampBox(byKey.get(key)?.bbox);
    if (!box || !scale) return;
    anchor.current = { cx: (box[0] + box[2]) / 2, cy: (box[1] + box[3]) / 2 };
    autoFit.current = false;
    setScale(Math.min(3, scale * 32 / Math.max(rowPitch, 4)));
    announce("Đã phóng to bảng. Chạm lại vào ô cần xem.");
  };
  const numPages = pdf?.numPages ?? report?.page_count ?? 0;

  useEffect(() => {
    const onKey = (event) => {
      if (event.target.closest?.("input, textarea, [contenteditable]")) return;
      // A panel, dialog, menu or tour on top handles its own keys first.
      if (document.querySelector(".rd-panel, .rd-modal-back, .rd-tour, .rd-popover")) return;
      if (event.key === "Escape") {
        if (pick) onPickCancel?.();
        else if (cardHere) closeCard();
        else if (selection.length) onSelect?.([]);
        else onClearFocus?.();
        return;
      }
      // Inside a table the arrows move between cells, not pages.
      if (event.defaultPrevented || event.target.closest?.('[role="gridcell"], .rd-cellcard, .rd-chart')) return;
      if (event.key === "ArrowRight" && pdf && page < pdf.numPages) goToPage(page + 1);
      if (event.key === "ArrowLeft" && page > 1) goToPage(page - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pdf, page, onClearFocus, cardHere, closeCard, selection.length, onSelect, pick, onPickCancel]);


  return <section className="rd-stage" aria-label="Trang báo cáo">
    {pdf && pdf.numPages > 1 && <nav className="rd-rail" aria-label="Các trang">
      {Array.from({ length: pdf.numPages }, (_, index) => <Thumb key={index} pdf={pdf} number={index + 1} active={page === index + 1} marked={markedPages?.has(index + 1)} onOpen={goToPage} />)}
    </nav>}
    {pick && <div className={`rd-focusbar rd-pickbar${pick.preview?.warning ? " unsure" : ""}`}>
      {/* Two fixed lines: the bar never changes height while you move over cells, so the page does not move under the pointer. */}
      {/* A doubtful cell shows why on the first line, before the reader chooses it. */}
      <p>{pick.preview?.warning
        ? <span className="rd-pick-line rd-pick-warn" title={pick.preview.warning}><i className="rd-mark unsure" aria-hidden="true">?</i>{pick.preview.warning}</span>
        : <span className="rd-pick-line"><b>Chọn ô đúng</b> thay cho <span className="rd-tok" style={{ "--part": partColor(pick.index) }}><InputTag index={pick.index} />{pick.value}</span><span className="rd-pick-name">{pick.label}.</span></span>}
        {pick.preview
          ? <span className="rd-pick-line rd-pick-preview" title={pick.preview.text}>{pick.preview.text}</span>
          : <span className="rd-pick-line rd-pick-hint">{pick.touch ? "Chạm một ô để xem kết quả mới." : "Rê chuột qua một ô để xem kết quả mới, bấm để dùng."}</span>}</p>
      {pick.touch && pick.preview?.key && !pick.preview.refused && <button type="button" className="rd-button primary" onClick={() => onPickChoose?.(pick.preview.key)}>Dùng ô này</button>}
      <button type="button" className="rd-button" onClick={onPickCancel}>{pick.touch ? "Huỷ" : "Huỷ (Esc)"}</button>
    </div>}
    {!pick && summary && <div className={`rd-focusbar rd-selbar${summary.caveats.length ? " unsure" : ""}`}>
      <button type="button" className="rd-focus-close" onClick={() => onSelect?.([])} aria-label="Bỏ chọn">×</button>
      <p><b>{summary.count} ô</b>{summary.additive && <><small>Tổng</small><b>{formatValue(String(Math.round(summary.sum * 100) / 100))}</b></>}<small>Trung bình</small><b>{formatValue(String(Math.round(summary.average * 10) / 10))}</b>{summary.change != null && <><small>{summary.changeFrom && summary.changeTo ? `Thay đổi từ ${summary.changeFrom} sang ${summary.changeTo}` : "Thay đổi"}</small><b>{summary.change >= 0 ? "+" : ""}{formatValue(String(Math.round(summary.change * 100) / 100))}%</b></>}
        {summary.caveats.map((caveat) => <span key={caveat} className="rd-caveat"><i className="rd-mark unsure" aria-hidden="true">?</i>{caveat}</span>)}</p>
      {onAskSelection && <button type="button" className="rd-button" aria-expanded={askingSelection} aria-controls="rd-asksugs" onClick={onAskSelection}>Hỏi về các ô này</button>}
      {onChartSelection && <button type="button" className="rd-button" onClick={onChartSelection}>Vẽ biểu đồ</button>}
    </div>}
    {!pick && !summary && !focus?.page && showRead && <div className="rd-focusbar rd-coverbar"><p><i className="rd-cover-swatch" aria-hidden="true" />Nền xám: số mình đã đọc được ({pageRead.length} số ở trang này). Số không được tô là số mình chưa đọc.</p></div>}
    {!pick && !summary && focus?.page && <div key={focus.nonce} className={`rd-focusbar${focus.unsure ? " unsure" : ""}`}>
      <button type="button" className="rd-focus-close" onClick={onClearFocus} aria-label="Bỏ đánh dấu">×</button>
      {focus.formula && formulaShown
        ? <p className="rd-parts">{focus.value && <b>{focus.value}</b>}<FormulaLine formula={focus.formula} result={focus.result} onPeek={onPeek} /><small>trang {focus.page}</small></p>
        : focus.parts?.length > 1
        ? <p className="rd-parts">{focus.value && <b>{focus.value}</b>}<small>tính từ</small>{focus.parts.map((part, i) => <span key={i} className="rd-tok" style={{ "--part": partColor(part.index ?? i) }} {...peekProps(part.key, onPeek)}><InputTag index={part.index ?? i} />{part.value}{part.label && <em>{part.label}</em>}</span>)}<small>trang {focus.page}</small></p>
        : <p>{focus.value && <b>{focus.value}</b>}<span>{focus.label || "Vị trí trong báo cáo"} · trang {focus.page}{showRaw(focus) && <> · PDF ghi <q>{focus.raw}</q></>}{focus.unsure ? " · mình chưa chắc số này, bạn so với trang giúp nhé" : ""}</span></p>}
      {onFocusPage && !rects.length && size && <small>Không có vị trí chính xác cho mục này</small>}
      {!onFocusPage && <button type="button" className="rd-button" onClick={() => goToPage(focus.page)}>Về trang {focus.page}</button>}
      {focusProblem && onDismissCheck && <button type="button" className="rd-button" onClick={() => onDismissCheck(focusProblem)}>Không phải lỗi</button>}
    </div>}
    <div className="rd-scroll" ref={scrollRef}>
      {!pdf && !error && <div className="rd-page-skeleton" aria-hidden="true" />}
      {error && <p className="rd-stage-error" role="alert">Không mở được PDF này. {error}</p>}
      <div className="rd-page" style={size ? { width: size.width, height: size.height } : undefined}>
        <canvas ref={canvasRef} />
        {processing && pdf && <div className="rd-scan" aria-hidden="true"><span /><em><i className="rd-spinner small" />Đang đọc trang này…</em></div>}
        {rects.length > 0 && <svg className={`rd-spotlight${focus?.unsure ? " unsure" : ""}`} width={size.width} height={size.height} onClick={onClearFocus} role="presentation">
          {bands && <g className="rd-bands">{[bands.row, bands.column].map((band, i) => { const r = toRect(band, 2); return <rect key={i} x={r.x} y={r.y} width={r.w} height={r.h} rx="3" />; })}</g>}
          {rects.map((r, i) => <rect key={`${focus.nonce}-${i}`} className="rd-cell" x={r.x} y={r.y} width={r.w} height={r.h} rx="3" style={multi ? { "--part": partColor(focus.parts[i].index ?? i) } : undefined} data-part={multi ? i : undefined} />)}
          {/* Numbered tags left of each input, the same numbers as in the card and the bar. */}
          {multi && rects.map((r, i) => <g key={`t-${focus.nonce}-${i}`} className="rd-page-tag" style={{ "--part": partColor(focus.parts[i].index ?? i), "--part-ink": partInk(focus.parts[i].index ?? i) }}><circle cx={r.x - 12} cy={r.y + r.h / 2} r="8" /><text x={r.x - 12} y={r.y + r.h / 2 + 3.5}>{(focus.parts[i].index ?? i) + 1}</text></g>)}
        </svg>}
        {size && <svg className="rd-marks" width={size.width} height={size.height} aria-hidden="true">
          {pageRead.map((cell) => { const r = pxBox(cell, 1); return <rect key={`r-${cell.evidence_key}`} className="rd-mark-read" x={r.x} y={r.y} width={r.w} height={r.h} rx="2" />; })}
          {picked.filter((cell) => cell.page_number === page && clampBox(cell.bbox)).map((cell) => { const r = pxBox(cell, 1); return <rect key={`s-${cell.evidence_key}`} className="rd-mark-selected" x={r.x} y={r.y} width={r.w} height={r.h} rx="2" />; })}
          {/* Badges sit left of the number, never over its digits. */}
          {pageProblems.map((cell) => { const r = pxBox(cell, 2); return <g key={`p-${cell.evidence_key}`} className="rd-mark-problem"><rect x={r.x} y={r.y} width={r.w} height={r.h} rx="2" /><circle cx={r.x - 10} cy={r.y + r.h / 2} r="8" /><text x={r.x - 10} y={r.y + r.h / 2 + 3.5}>!</text></g>; })}
          {pick && pickCells.map((cell) => { const r = pxBox(cell, 2); return <rect key={`c-${cell.evidence_key}`} className="rd-mark-cand" x={r.x} y={r.y} width={r.w} height={r.h} rx="2" />; })}
          {outline && (() => { const r = pxBox(outline, 3); return <rect className="rd-mark-peek" x={r.x} y={r.y} width={r.w} height={r.h} rx="3" />; })()}
          {pageUnsure.map((cell) => { const r = pxBox(cell, 0); return <g key={`u-${cell.evidence_key}`} className="rd-mark-unsure"><rect x={r.x} y={r.y} width={r.w} height={r.h} rx="2" /><circle cx={r.x - 10} cy={r.y + r.h / 2} r="7.5" /><text x={r.x - 10} y={r.y + r.h / 2 + 3.5}>?</text></g>; })}
        </svg>}
        {size && tables.length > 0 && <CellLayer tables={tables} size={size} page={page} openKey={openKey} selection={selection} selectMode={selectMode}
          picking={Boolean(pick)} pickHover={pick?.preview?.key ?? null} onPickHover={(key, byKeyboard) => { pickByKeys.current = Boolean(byKeyboard); onPickHover?.(key); }} onPickChoose={(key) => onPickChoose?.(key)} onOpen={(key) => onOpenCell?.(key)} onSelect={(keys) => onSelect?.(keys)} onAnnounce={announce} onBlank={() => { onSelect?.([]); onCloseCard?.(); onClearFocus?.(); }} onDenseTap={zoomToCell} />}
        {size && prose.length > 0 && <ProseLayer cells={prose} size={size} page={page} openKey={openKey} picking={Boolean(pick)} pickHover={pick?.preview?.key ?? null}
          onPickHover={(key, byKeyboard) => { pickByKeys.current = Boolean(byKeyboard); onPickHover?.(key); }} onPickChoose={(key) => onPickChoose?.(key)} onOpen={(key) => onOpenCell?.(key)} />}
        {cardPlace && renderCard && <div className="rd-cellcard-anchor" style={{ left: cardPlace.left, top: cardPlace.top, "--notch": `${cardPlace.notch}px` }}>{renderCard(openCell, { narrow: false, onClose: closeCard })}</div>}
      </div>
    </div>
    {cardHere && narrow && renderCard && <div className="rd-cellsheet">{renderCard(openCell, { narrow: true, onClose: closeCard })}</div>}
    <p className="rd-sr" aria-live="polite">{live}</p>
    <div className="rd-stage-tools" role="toolbar" aria-label="Điều khiển trang">
      <button type="button" onClick={() => goToPage(Math.max(1, page - 1))} disabled={page <= 1} aria-label="Trang trước">‹</button>
      <span><span className="rd-page-word">Trang </span>{page} / {numPages || "…"}</span>
      <button type="button" onClick={() => pdf && goToPage(Math.min(pdf.numPages, page + 1))} disabled={!pdf || page >= pdf.numPages} aria-label="Trang sau">›</button>
      <i aria-hidden="true" />
      <button type="button" onClick={() => zoom(-0.15)} aria-label="Thu nhỏ">−</button>
      <span className="rd-zoom" aria-live="polite">{scale ? `${Math.round(scale * 100)}%` : ""}</span>
      <button type="button" onClick={() => zoom(0.15)} aria-label="Phóng to">+</button>
      <div className="rd-stage-modes">
        <button type="button" onClick={() => { autoFit.current = true; fit(); }} className="rd-fit">Vừa khung</button>
        {evidences.length > 0 && <button type="button" className="rd-fit" aria-pressed={showRead} onClick={toggleRead} title="Tô các số mình đã đọc được. Số không được tô là số mình chưa đọc.">Tô số đã đọc</button>}
        {tables.length > 0 && <button type="button" className="rd-fit" aria-pressed={selectMode} onClick={() => setSelectMode((value) => !value)} title="Kéo để chọn nhiều ô">Chọn vùng</button>}
      </div>
    </div>
  </section>;
}
