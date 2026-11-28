// "Đổi ô": the reader replaces one input of an answer's calculation with
// another cell, sees the new result before choosing, and can undo. The server
// runs the answer's own stored script again; nothing is saved on the answer.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { cellName, cellNumber, pickCandidates, pickWarning } from "./cells.js";
import { formatNumber } from "./format.js";
import { swappedHeadline } from "./Notes.jsx";

const coarse = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(pointer: coarse)").matches);
// Moving over a table should not start a calculation per cell crossed.
const HOVER_DELAY_MS = 150;

export function useSwaps({ basePath, evidences, dataKey, focusOn, toast }) {
  const [swaps, setSwaps] = useState({});
  const [pick, setPick] = useState(null);
  // An answer whose swap is being calculated: "Đổi ô" waits, so two swaps never overwrite each other.
  const [busy, setBusy] = useState(null);
  const cache = useRef(new Map());
  // Bumped on every reset: a reply that comes back after it belongs to old numbers or another report.
  const generation = useRef(0);
  const pickCount = useRef(0);
  const pickRef = useRef(null);
  pickRef.current = pick;
  const swapsRef = useRef(swaps);
  swapsRef.current = swaps;
  const hoverTimer = useRef(0);
  const hoverAbort = useRef(null);
  const returnFocus = useRef(null);
  const byKey = useMemo(() => new Map(evidences.map((item) => [item.evidence_key, item])), [evidences]);

  const stopHover = () => { window.clearTimeout(hoverTimer.current); hoverAbort.current?.abort(); hoverAbort.current = null; };
  // New numbers (a correction) or another report make every swapped result stale.
  useEffect(() => { generation.current += 1; stopHover(); setSwaps({}); setPick(null); setBusy(null); cache.current.clear(); }, [dataKey, basePath]);
  useEffect(() => stopHover, []);

  const restoreFocus = () => {
    const node = returnFocus.current;
    returnFocus.current = null;
    if (node?.isConnected) window.requestAnimationFrame(() => node.focus({ preventScroll: true }));
  };

  // messageId is the answer's own message; a note is keyed by its question.
  const run = useCallback((messageId, formulaIndex, swap, signal) => {
    const id = JSON.stringify([messageId, formulaIndex, Object.entries(swap).sort()]);
    if (!cache.current.has(id)) {
      cache.current.set(id, request(`${basePath}/recalculate`, { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message_id: messageId, formula_index: formulaIndex, swap }) })
        .then((body) => {
          // Only a real answer is kept: a body cut off by an abort reads as {} and must not stick.
          if (signal?.aborted || !body?.status) { cache.current.delete(id); throw new Error("Chưa tính xong"); }
          return body;
        })
        .catch((error) => { cache.current.delete(id); throw error; }));
    }
    return cache.current.get(id);
  }, [basePath]);

  const start = useCallback(({ note, base, headline, formulaIndex, index }) => {
    if (busy) return;
    const key = headline.formula.inputs[index]?.evidence_key;
    const cell = byKey.get(key);
    if (!cell) return;
    const swap = swapsRef.current[note.id]?.swap ?? {};
    const original = Object.keys(swap).find((from) => swap[from] === key) ?? key;
    const used = headline.formula.inputs.map((input) => input.evidence_key);
    returnFocus.current = document.activeElement;
    stopHover();
    pickCount.current += 1;
    setPick({ id: pickCount.current, noteId: note.id, messageId: note.reply.id, formulaIndex, index, key, original, base, swap, used, preview: null, candidates: pickCandidates(cell, evidences, used).map((item) => item.evidence_key) });
    focusOn({ page: cell.page_number, boxes: cell.bbox ? [cell.bbox] : [], label: cellName(cell), value: formatNumber(cell.current_numeric_value), key });
  }, [busy, byKey, evidences, focusOn]);

  /** Why a cell cannot take this input's place, or "" when it can. */
  const refusal = (current, key) => {
    const cell = byKey.get(key);
    if (!cell || cellNumber(cell) == null) return "Ô này không có số, chọn ô khác.";
    // The calculation only reads numbers it can vouch for: an unclear reading must be fixed first.
    if (cell.data_status !== "valid") return "Ô này có thể đọc sai. Sửa số trước.";
    if (key !== current.original && current.used.includes(key)) return "Ô này đã có trong phép tính, chọn ô khác.";
    return "";
  };

  const resultWith = useCallback(async (current, key, signal) => {
    const swap = { ...current.swap, [current.original]: key };
    if (key === current.original) delete swap[current.original];
    const response = await run(current.messageId, current.formulaIndex, swap, signal);
    // The calculation itself refused these cells: not worth trying again. The server's own error text is for logs.
    if (response.status !== "succeeded") throw Object.assign(new Error("Phép tính không chạy được với ô này, chọn ô khác."), { refused: true });
    return { swap, formula: response.formula, headline: swappedHeadline(current.base, response.formula) };
  }, [run]);

  const hover = useCallback((key) => {
    const current = pickRef.current;
    stopHover();
    if (!current) return;
    if (!key || key === current.key) { setPick((p) => p && { ...p, preview: null }); return; }
    const refused = refusal(current, key);
    if (refused) { setPick((p) => p && { ...p, preview: { key, text: refused, refused: true } }); return; }
    const cell = byKey.get(key);
    const warning = pickWarning(byKey.get(current.key), cell);
    // The result comes first: on a narrow bar the end of the line is cut off.
    const tail = ` nếu chọn ${formatNumber(cell.current_numeric_value)} (${cellName(cell)})`;
    const same = (p) => p?.id === current.id && p.preview?.key === key;
    setPick((p) => p && { ...p, preview: { key, text: `Kết quả …${tail}`, warning } });
    const gen = generation.current;
    hoverTimer.current = window.setTimeout(() => {
      const controller = new AbortController();
      hoverAbort.current = controller;
      resultWith(current, key, controller.signal)
        .then(({ headline }) => { if (gen === generation.current) setPick((p) => (same(p) ? { ...p, preview: { key, text: `Kết quả ${headline.value}${tail}`, warning } } : p)); })
        .catch((error) => {
          if (controller.signal.aborted || gen !== generation.current) return;
          // A busy server or a dropped connection is not a refusal: the reader can still choose the cell.
          const text = error.refused ? error.message : "Không xem trước được";
          setPick((p) => (same(p) ? { ...p, preview: { key, text, warning, refused: Boolean(error.refused) } } : p));
        });
    }, HOVER_DELAY_MS);
  }, [byKey, resultWith]);

  const choose = useCallback(async (key) => {
    const current = pickRef.current;
    if (!current) return;
    // Keep a preview request running: choosing the previewed cell reuses its answer.
    window.clearTimeout(hoverTimer.current);
    hoverAbort.current = null;
    if (key === current.key) { setPick(null); restoreFocus(); return; }
    const refused = refusal(current, key);
    if (refused) { setPick((p) => p && { ...p, preview: { key, text: refused, refused: true } }); return; }
    setPick(null);
    setBusy(current.noteId);
    const gen = generation.current;
    try {
      const { swap, formula, headline } = await resultWith(current, key);
      if (gen !== generation.current) return;
      const changes = Object.entries(swap).map(([from, to]) => ({ from: cellName(byKey.get(from)), to: cellName(byKey.get(to)) }));
      const warning = Object.entries(swap).map(([from, to]) => pickWarning(byKey.get(from), byKey.get(to))).find(Boolean) ?? "";
      setSwaps((all) => {
        const next = { ...all };
        // The original result's chip: undo shows it on the page again.
        if (changes.length) next[current.noteId] = { formulaIndex: current.formulaIndex, swap, formula, warning, changes, baseChip: current.base.chip };
        else delete next[current.noteId];
        return next;
      });
      focusOn(headline.chip);
      toast({ text: changes.length ? `Đã đổi ô. Kết quả mới ${headline.value}.` : "Đã hoàn tác" });
    } catch (error) {
      if (gen === generation.current) toast({ kind: "error", text: error.refused ? error.message : `Không tính lại được. ${error.message}` });
    } finally {
      if (gen === generation.current) { setBusy(null); restoreFocus(); }
    }
  }, [byKey, resultWith, focusOn, toast]);

  const cancel = useCallback(() => { stopHover(); setPick(null); restoreFocus(); }, []);

  const undo = useCallback((noteId) => {
    const base = swapsRef.current[noteId]?.baseChip;
    setSwaps((all) => { const next = { ...all }; delete next[noteId]; return next; });
    // The page showed the swapped calculation: it goes back to the answer's own cells.
    if (base) focusOn(base);
    toast({ text: "Đã hoàn tác" });
  }, [focusOn, toast]);

  // What the page shows while choosing.
  const view = pick && {
    key: pick.key,
    index: pick.index,
    value: formatNumber(byKey.get(pick.key)?.current_numeric_value),
    label: cellName(byKey.get(pick.key)),
    preview: pick.preview,
    candidates: pick.candidates,
    touch: coarse(),
  };
  return { swaps, pick: view, busy, start, hover, choose, cancel, undo };
}
