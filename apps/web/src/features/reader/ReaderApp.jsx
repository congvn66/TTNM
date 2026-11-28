import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { useTheme } from "../theme/ThemeProvider.jsx";
import { AskBox } from "./AskBox.jsx";
import { ConfirmDialog, DropOverlay, HelpDialog, RenameDialog, Sidebar, Toasts, TopBar } from "./Chrome.jsx";
import { DataPanel } from "./DataPanel.jsx";
import { Home, SAMPLE_URL } from "./Home.jsx";
import { AnswerCard, BriefCard, FailedCard, PendingCard, ReadingCard, showNumber } from "./Notes.jsx";
import { CellCard } from "./CellCard.jsx";
import { ChartCard } from "./ChartCard.jsx";
import { chartData, loadCharts, MAX_CHARTS, saveCharts } from "./charts.js";
import { cellName, cellUnsure, selectionQuestions } from "./cells.js";
import { formatNumber as formatValue, scrollBehavior } from "./format.js";
import { PdfStage } from "./PdfStage.jsx";
import { isOpenProblem, useDismissed } from "./dismissed.js";
import { buildBriefing } from "./reportChecks.js";
import { setSoundEnabled, soundEnabled, unlockSound, useReadySignal } from "./signals.js";
import { isProcessing, useReports } from "./useReports.js";
import { useConversation } from "./useConversation.js";
import { useSwaps } from "./useSwaps.js";
import "./reader.css";

/** The re-read toast: old answers that used a changed number need asking again (from the audit). */
export function rereadSummary(report) {
  const flagged = report.extraction_history?.at(-1)?.affected_message_ids?.length ?? 0;
  return `Đã đọc lại ${report.file_name}${flagged ? ` · ${flagged} câu trả lời cần hỏi lại` : ""}`;
}

function firstDataSource(reply) {
  const item = (reply?.structured_answer?.evidence ?? []).find((evidence) => evidence.kind === "data" && evidence.page);
  return item ? { page: item.page, boxes: item.bbox ? [item.bbox] : [], label: item.label, value: showNumber(item.value ?? item.raw_text), key: item.evidence_key, unsure: Boolean(item.data_status && item.data_status !== "valid") } : null;
}

const SIDEBAR_KEY = "sourcelens-sidebar";
const narrowScreen = () => Boolean(window.matchMedia?.("(max-width: 900px)").matches);
function initialSidebar() {
  if (narrowScreen()) return false;
  try { return localStorage.getItem(SIDEBAR_KEY) !== "0"; } catch { return true; }
}

export default function ReaderApp({ user = null, onSignOut = null, onNavigate }) {
  const { preference, setPreference } = useTheme();
  const reports = useReports();
  const { selected } = reports;
  const conversation = useConversation(selected);
  const [focus, setFocus] = useState(null);
  const [openCell, setOpenCell] = useState(null);
  const [selection, setSelection] = useState([]);
  const [askingSelection, setAskingSelection] = useState(false);
  const [question, setQuestion] = useState("");
  const [toasts, setToasts] = useState([]);
  const [helpOpen, setHelpOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [evidence, setEvidence] = useState({ key: null, data: null, loading: false });
  const [revision, setRevision] = useState(0);
  const [sound, setSound] = useState(soundEnabled);
  const [sidebarOpen, setSidebarOpenState] = useState(initialSidebar);
  const setSidebarOpen = useCallback((open) => {
    setSidebarOpenState(open);
    if (!narrowScreen()) { try { localStorage.setItem(SIDEBAR_KEY, open ? "1" : "0"); } catch { /* storage blocked */ } }
  }, []);
  // On a phone the sidebar is a drawer: it closes after a pick.
  const pickReport = useCallback((id) => { reports.select(id); if (narrowScreen()) setSidebarOpenState(false); }, [reports, setSidebarOpen]);
  const [renaming, setRenaming] = useState(null);
  const [confirm, setConfirm] = useState(null);
  // The calculation input under the pointer or keyboard focus, outlined on the page.
  const [peekKey, setPeekKey] = useState(null);
  // Charts drawn from selections, per report, kept in this browser.
  // Tagged with their report, so one render after switching never draws the old report's charts on the new numbers.
  const [chartState, setChartState] = useState({ report: null, list: [] });
  // The chart bar a cell card was opened from, to return to when it closes.
  const chartReturn = useRef(null);
  const askRef = useRef(null);
  const notesRef = useRef(null);
  const uploadRef = useRef(null);

  const toast = useCallback((item) => {
    const id = `${Date.now()}-${Math.random()}`;
    // A toast with a group replaces the earlier toast of that group ("uploaded" gives way to "ready").
    setToasts((items) => [...items.filter((entry) => !item.group || entry.group !== item.group).slice(-2), { ...item, id }]);
    window.setTimeout(() => setToasts((items) => items.filter((entry) => entry.id !== id)), item.kind === "error" ? 9000 : 6000);
  }, []);
  const closeToast = useCallback((id) => setToasts((items) => items.filter((entry) => entry.id !== id)), []);

  const focusOn = useCallback((next) => {
    setFocus(next?.page ? { ...next, nonce: Date.now() } : null);
    // On narrow screens the page sits above the notes: bring it into view.
    if (next?.page && window.matchMedia?.("(max-width: 1000px)").matches) document.querySelector(".rd-stage-wrap")?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  }, []);
  const clearFocus = useCallback(() => setFocus(null), []);
  useEffect(() => { setChartState({ report: selected?.id ?? null, list: selected ? loadCharts(selected.id) : [] }); setPeekKey(null); }, [selected?.id]);
  const charts = chartState.report === selected?.id ? chartState.list : [];
  const changeCharts = useCallback((update) => setChartState((state) => {
    if (!selected || state.report !== selected.id) return state;
    const list = update(state.list);
    saveCharts(selected.id, list);
    return { ...state, list };
  }), [selected?.id]);
  useEffect(() => { setFocus(null); setOpenCell(null); setSelection([]); setAskingSelection(false); setQuestion(""); setDataOpen(false); document.title = selected ? `${selected.file_name} · SourceLens` : "SourceLens"; }, [selected?.id]);

  useReadySignal(reports.reports, useCallback((event) => {
    const mine = event.report.id === selected?.id;
    if (event.kind === "ready" && (event.report.extraction_history?.length ?? 0) > 1) {
      toast({ kind: "ready", group: `report-${event.report.id}`, text: rereadSummary(event.report) });
    } else if (event.kind === "ready") {
      toast({ kind: "ready", group: `report-${event.report.id}`, text: `${event.report.file_name} đã sẵn sàng`, action: mine ? null : { label: "Mở", onClick: () => reports.select(event.report.id) } });
      if (mine) window.setTimeout(() => askRef.current?.focus(), 300);
    } else {
      toast({ kind: "error", group: `report-${event.report.id}`, text: `Không đọc được ${event.report.file_name}.` });
    }
  }, [selected?.id, toast, reports]));

  // One fetch of the numbers feeds both the briefing and the data panel.
  const ready = selected?.extraction_status === "ready";
  // A re-read changes the numbers, so its result count is part of the key.
  const evidenceKey = ready ? `${selected.id}:${revision}:${selected.numeric_evidence_count ?? ""}:${selected.extraction_history?.length ?? 0}` : null;
  useEffect(() => {
    if (!evidenceKey || evidence.key === evidenceKey) return;
    let live = true;
    // A reload of the same report keeps the old numbers on screen until the new ones arrive: charts and the data panel do not blink empty.
    setEvidence((prev) => ({ key: evidenceKey, data: prev.key?.split(":")[0] === selected.id ? prev.data : null, loading: true }));
    request(`/api/v1/sessions/${selected.sessionId}/documents/${selected.id}/evidences`)
      .then((data) => { if (live) setEvidence({ key: evidenceKey, data, loading: false }); })
      .catch(() => { if (live) setEvidence({ key: evidenceKey, data: null, loading: false }); });
    return () => { live = false; };
  }, [evidenceKey]);
  // The AI overview: made once per reading of the report and stored by the server.
  const [brief, setBrief] = useState({ key: null, status: "idle" });
  const briefKey = ready ? `${selected.id}:${selected.extraction_history?.length ?? 0}` : null;
  const loadBrief = useCallback(async (key, report) => {
    setBrief({ key, status: "loading" });
    try {
      const base = `/api/v1/sessions/${report.sessionId}/documents/${report.id}/brief`;
      let result = await request(base);
      if (result?.status !== "ready") result = await request(base, { method: "POST" });
      const answer = result?.brief?.structured_answer;
      if (!answer) throw new Error("Không tải được bản tóm tắt.");
      setBrief((current) => current.key === key ? { key, status: "ready", answer } : current);
    } catch (error) {
      setBrief((current) => current.key === key ? { key, status: error.code === "BRIEF_UNAVAILABLE" ? "unavailable" : "error", error: { message: error.message, code: error.code, status: error.status, detail: error.detail } } : current);
    }
  }, []);
  useEffect(() => { if (briefKey && brief.key !== briefKey) loadBrief(briefKey, selected); }, [briefKey]);

  const briefing = useMemo(() => evidence.data && evidence.key === evidenceKey ? buildBriefing(evidence.data.evidences ?? []) : null, [evidence, evidenceKey]);
  const problems = useDismissed(selected?.id);
  const currentEvidences = useMemo(() => (selected && evidence.key?.startsWith(`${selected.id}:`) ? evidence.data?.evidences ?? [] : []), [selected, evidence]);
  // The paragraphs that hold a number, by key: a text number's card shows its sentence.
  const paragraphs = useMemo(() => new Map((selected && evidence.key?.startsWith(`${selected.id}:`) ? evidence.data?.paragraphs ?? [] : []).map((item) => [item.paragraph_key, item])), [selected, evidence]);
  const swaps = useSwaps({ basePath: selected ? `/api/v1/sessions/${selected.sessionId}/documents/${selected.id}` : "", evidences: currentEvidences, dataKey: evidence.key, focusOn, toast });
  // Checks the reader has not dismissed: the page marks, the cell card and the page rail use these.
  const openChecks = useMemo(() => (briefing?.checks ?? []).filter((check) => check.ok || isOpenProblem(check, problems.dismissed)), [briefing, problems.dismissed]);

  // A fresh answer lights up its first number on the page by itself.
  const seenReplies = useRef({ report: null, ids: new Set() });
  useEffect(() => {
    if (!selected || conversation.loadedId !== selected.id) return;
    const replies = conversation.notes.map((note) => note.reply).filter(Boolean);
    if (seenReplies.current.report !== selected.id) { seenReplies.current = { report: selected.id, ids: new Set(replies.map((reply) => reply.id)) }; return; }
    const seen = seenReplies.current.ids;
    const fresh = replies.filter((reply) => !seen.has(reply.id) && reply.status !== "processing");
    fresh.forEach((reply) => seen.add(reply.id));
    if (!fresh.length) return;
    // Show the start of the newest answer.
    window.requestAnimationFrame(() => { const node = notesRef.current; const card = node?.querySelector(".rd-qa:last-of-type"); if (node && card) node.scrollTo({ top: card.offsetTop - 12, behavior: scrollBehavior() }); });
    const source = firstDataSource(fresh.at(-1));
    if (source) focusOn(source); else setFocus(null);
  }, [conversation.notes, conversation.loadedId, selected, focusOn]);

  // Opening a report shows the top; asking scrolls to the newest card.
  useEffect(() => { notesRef.current?.scrollTo({ top: 0 }); }, [selected?.id]);
  useEffect(() => {
    const node = notesRef.current;
    if (node && conversation.pending.length) node.scrollTo({ top: node.scrollHeight, behavior: scrollBehavior() });
  }, [conversation.pending.length]);

  const upload = useCallback(async (file) => {
    if (!file) return;
    unlockSound();
    try {
      const document = await reports.upload(file);
      if (document) toast({ group: `report-${document.id}`, text: `Đang đọc ${document.file_name}…` });
    } catch (error) {
      toast({ kind: "error", text: error.message });
    }
  }, [reports, toast]);

  const useSample = useCallback(async () => {
    unlockSound();
    try {
      const blob = await (await fetch(SAMPLE_URL)).blob();
      await upload(new File([blob], "bao-cao-mau-huong-lua.pdf", { type: "application/pdf" }));
    } catch (error) {
      toast({ kind: "error", text: "Không mở được báo cáo mẫu." });
    }
  }, [upload, toast]);

  const ask = useCallback(async (text) => {
    if (!text.trim() || !selected) return;
    setQuestion("");
    await conversation.ask(text);
  }, [conversation, selected]);

  const onEvidenceSaved = useCallback(async (_item, result) => {
    setRevision((value) => value + 1);
    await conversation.reload().catch(() => {});
    const affected = result?.affected_message_ids?.length ?? 0;
    toast({ text: affected ? `Đã lưu · ${affected} câu trả lời cần hỏi lại` : "Đã lưu" });
  }, [conversation, toast]);

  // Re-reading is offered only where the server says it can do it.
  const [canReread, setCanReread] = useState(false);
  useEffect(() => {
    let live = true;
    request("/health").then((health) => { if (live) setCanReread(health?.capabilities?.reextraction?.status === "available"); }).catch(() => {});
    return () => { live = false; };
  }, []);

  // Stop an answer the background worker is still writing.
  const stopAnswer = useCallback(async (reply) => {
    try {
      const jobs = (await request("/api/v1/jobs")).jobs ?? [];
      const job = jobs.find((item) => item.kind === "answer_question" && item.payload?.assistant_message_id === reply.id && ["queued", "running"].includes(item.status));
      if (job) await request(`/api/v1/jobs/${job.id}/cancel`, { method: "POST" });
      await conversation.reload();
      if (job) toast({ text: "Đã dừng" });
    } catch (error) {
      toast({ kind: "error", text: error.message });
    }
  }, [conversation, toast]);

  // The Library page sends people here with ?upload=1 to add a report.
  // It waits for the reports to load (the upload box does not exist before) and shows the home
  // screen with its drop zone; the file picker opens only while the browser still counts the
  // Library click as the person's action, since a picker opened by script alone is blocked.
  useEffect(() => {
    if (reports.loading) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("upload") !== "1") return;
    params.delete("upload");
    window.history.replaceState({}, "", `${window.location.pathname}${params.toString() ? `?${params}` : ""}`);
    reports.select(null);
    if (navigator.userActivation?.isActive !== false) window.setTimeout(() => uploadRef.current?.click(), 0);
  }, [reports.loading]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.target.closest?.("input, textarea, [contenteditable]")) return;
      if (event.key === "/" && selected) { event.preventDefault(); askRef.current?.focus(); }
      if (event.key === "?") { event.preventDefault(); setHelpOpen(true); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  const confirmReread = () => setConfirm({
    title: "Đọc lại báo cáo này?",
    text: "Các số bạn đã sửa sẽ được giữ lại nếu còn đúng chỗ.",
    confirmLabel: "Đọc lại",
    busyLabel: "Đang đọc lại…",
    onConfirm: () => reports.reextract(selected).then(() => toast({ group: `report-${selected.id}`, text: "Đang đọc lại…" })).catch((error) => toast({ kind: "error", text: error.message })),
  });
  const confirmDelete = (report) => setConfirm({
    title: `Xóa ${report.file_name}?`,
    text: "Các câu hỏi về báo cáo này cũng bị xóa.",
    confirmLabel: "Xóa",
    busyLabel: "Đang xóa…",
    danger: true,
    onConfirm: () => reports.remove(report).then(() => toast({ text: `Đã xóa ${report.file_name}` })).catch((error) => toast({ kind: "error", text: error.message })),
  });
  const menuItems = [
    { label: "Số liệu", onClick: () => setDataOpen(true), disabled: !ready },
    { label: "Đổi tên", onClick: () => setRenaming(selected) },
    canReread && { label: "Đọc lại", onClick: confirmReread },
    { label: "Xóa", danger: true, onClick: () => confirmDelete(selected) },
  ];


  const askedQuestions = useMemo(() => new Set([...conversation.notes.map((note) => note.question?.body?.trim()), ...conversation.pending.map((item) => item.question.trim())].filter(Boolean)), [conversation.notes, conversation.pending]);

  const markedPages = useMemo(() => {
    const pages = new Set();
    conversation.notes.forEach((note) => (note.reply?.structured_answer?.evidence ?? []).forEach((item) => item.page && pages.add(item.page)));
    openChecks.filter((check) => !check.ok).forEach((check) => pages.add(check.chip.page));
    return pages;
  }, [conversation.notes, openChecks]);

  if (reports.loading) return <div className="rd-app"><div className="rd-boot" role="status"><span className="rd-spinner large" aria-hidden="true" />Đang tải…</div></div>;
  if (reports.error && !reports.reports.length) return <div className="rd-app"><div className="rd-boot" role="alert"><h1>Không kết nối được</h1><button type="button" className="rd-button primary" onClick={() => window.location.reload()}>Thử lại</button></div></div>;

  const processing = isProcessing(selected);
  // Only this report's numbers: after switching reports the old list stays in state until the new one loads.
  const evidences = currentEvidences;
  const basePath = selected ? `/api/v1/sessions/${selected.sessionId}/documents/${selected.id}` : "";
  const openCellCard = (key) => {
    const cell = evidences.find((item) => item.evidence_key === key);
    if (!cell) return;
    chartReturn.current = null;
    setSelection([]); setAskingSelection(false); setOpenCell(key);
    focusOn({ page: cell.page_number, boxes: cell.bbox ? [cell.bbox] : [], label: cellName(cell), value: cell.current_numeric_value == null ? "—" : formatValue(cell.current_numeric_value), raw: cell.raw_text, key, unsure: cellUnsure(cell) });
  };
  const selectCells = (keys) => { setSelection(keys); setOpenCell(null); setAskingSelection(false); if (keys.length) setFocus(null); };
  const askAboutSelection = () => {
    setAskingSelection((open) => !open);
    // Suggestions appear above the ask box; move focus there without scrolling the page.
    window.requestAnimationFrame(() => document.querySelector(".rd-asksugs button")?.focus({ preventScroll: true }));
  };
  const selectionQuestionList = selection.length ? selectionQuestions(evidences.filter((item) => selection.includes(item.evidence_key)), evidences) : [];
  const selectionSuggestions = askingSelection ? selectionQuestionList : [];
  const canChart = selection.length > 1 && Boolean(chartData(selection, evidences));
  const drawChart = () => {
    const id = `${Date.now().toString(36)}`;
    // The selected cells of the chart's table, with their names: after a re-read a key may point at another cell, and the names catch that.
    // Cells the chart leaves out (a total, a margin row) stay in, so the chart can still say why they are not drawn.
    const data = chartData(selection, evidences);
    const kept = selection.map((key) => evidences.find((item) => item.evidence_key === key)).filter((cell) => cell?.table_locator?.table_region_key === data.tableKey && cell.page_number === data.page);
    const names = Object.fromEntries(kept.map((cell) => [cell.evidence_key, [cell.table_locator.row_header, cell.table_locator.column_header]]));
    if (charts.length >= MAX_CHARTS) toast({ text: "Đã xóa biểu đồ cũ nhất" });
    changeCharts((list) => [...list, { id, keys: kept.map((cell) => cell.evidence_key), names }].slice(-MAX_CHARTS));
    setSelection([]); setAskingSelection(false);
    // The new card takes focus, so a keyboard user lands on what was made.
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => { const card = document.getElementById(`chart-${id}`); card?.scrollIntoView({ behavior: scrollBehavior(), block: "nearest" }); card?.focus({ preventScroll: true }); card?.classList.add("rd-flash"); }));
  };
  // "Chọn lại các ô trên trang": go to the chart's page, select its cells, and bring the first one into view.
  const showChartCells = (keys) => {
    const here = keys.filter((key) => evidences.some((item) => item.evidence_key === key));
    const cell = evidences.find((item) => item.evidence_key === here[0]);
    if (!cell) return;
    focusOn({ page: cell.page_number, boxes: [], key: null });
    window.requestAnimationFrame(() => selectCells(here));
    // The page may still be drawing: look for the cell for up to a second.
    let tries = 0;
    const reveal = () => {
      const node = document.querySelector(`[data-cell="${CSS.escape(here[0])}"]`);
      if (node) { node.scrollIntoView({ block: "center", inline: "nearest", behavior: scrollBehavior() }); node.focus({ preventScroll: true }); } else if (tries++ < 10) window.setTimeout(reveal, 100);
    };
    window.setTimeout(reveal, 100);
  };
  // A cell opened from a chart bar: closing its card goes back to that bar, not to the page, so the reader keeps their place.
  const openFromChart = (key, chartId) => { openCellCard(key); chartReturn.current = { key, chartId }; };
  const closeCellCard = (how) => {
    setOpenCell(null);
    const back = chartReturn.current;
    chartReturn.current = null;
    if (!how?.byUser || !back) return;
    // Two frames: after the page has put focus on its own cell.
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      const bar = document.querySelector(`#chart-${CSS.escape(back.chartId)} [data-key="${CSS.escape(back.key)}"]`);
      bar?.scrollIntoView({ block: "nearest", behavior: scrollBehavior() });
      bar?.focus({ preventScroll: true });
    }));
  };
  const removeChart = (id) => {
    const at = charts.findIndex((item) => item.id === id);
    const removed = charts[at];
    changeCharts((list) => list.filter((item) => item.id !== id));
    setPeekKey(null);
    toast({ text: "Đã xóa biểu đồ", action: removed && { label: "Hoàn tác", onClick: () => changeCharts((list) => (list.some((item) => item.id === id) ? list : [...list.slice(0, at), removed, ...list.slice(at)])) } });
    window.requestAnimationFrame(() => askRef.current?.focus({ preventScroll: true }));
  };
  // The answer takes focus too, or a keyboard user is left on a card that just closed.
  const gotoAnswer = (id) => { setOpenCell(null); const card = document.getElementById(`note-${id}`); card?.scrollIntoView({ behavior: scrollBehavior(), block: "nearest" }); card?.focus({ preventScroll: true }); card?.classList.remove("rd-flash"); void card?.offsetWidth; card?.classList.add("rd-flash"); };
  const dismissProblem = (check) => {
    problems.dismiss(check.chip.key);
    if (focus?.key === check.chip.key) clearFocus();
    toast({ text: "Đã ẩn", action: { label: "Hoàn tác", onClick: () => problems.undismiss(check.chip.key) } });
    // The button pressed is gone: focus the next one, else "Hiện lại".
    window.requestAnimationFrame(() => (document.querySelector(".rd-alert .rd-dismiss") ?? document.querySelector(".rd-skipped button"))?.focus({ preventScroll: true }));
  };
  const renderCard = (cell, { narrow, onClose }) => <CellCard cell={cell} evidences={evidences} paragraph={paragraphs.get(cell.paragraph_locator?.paragraph_key) ?? null} notes={conversation.notes} checks={openChecks} basePath={basePath} narrow={narrow} onClose={onClose}
    onAsk={(text) => { setOpenCell(null); setQuestion(text); window.requestAnimationFrame(() => askRef.current?.focus()); }}
    onGotoAnswer={gotoAnswer} onGotoCheck={(check) => { const key = openCell; setOpenCell(null); focusOn(check.chip); window.requestAnimationFrame(() => document.querySelector(`[data-cell="${CSS.escape(key)}"]`)?.focus({ preventScroll: true })); }}
    onSaved={onEvidenceSaved} onConflict={() => setRevision((value) => value + 1)} />;
  return <div className={`rd-app${sidebarOpen ? " side-open" : ""}`}>
    <a className="rd-skip" href="#main-content">Bỏ qua điều hướng</a>
    <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} reports={reports.reports} selected={selected} onOpen={pickReport} onHome={() => pickReport(null)} onNew={() => uploadRef.current?.click()}
      onLibrary={user && onNavigate ? () => onNavigate("/app/library") : null} user={user} onSettings={() => onNavigate?.("/app/settings/profile")} onSignOut={onSignOut}
      theme={preference} onTheme={setPreference} sound={sound} onSound={() => { setSoundEnabled(!sound); setSound(!sound); }} />
    <TopBar selected={selected} sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(true)} onHelp={() => setHelpOpen(true)} menuItems={menuItems} />
    <input ref={uploadRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => { upload(event.target.files?.[0]); event.target.value = ""; }} />
    {reports.uploading
      ? <main className="rd-work" id="main-content">
        <div className="rd-stage-wrap"><div className="rd-boot" role="status"><span className="rd-spinner large" aria-hidden="true" />Đang tải lên {reports.uploading.name}…</div></div>
        <aside className="rd-notes" aria-label="Tiến độ tải lên"><div className="rd-notes-scroll"><ReadingCard uploading report={{ file_name: reports.uploading.name, created_at: reports.uploading.startedAt }} /></div></aside>
      </main>
      : !selected
      ? <Home onFile={upload} onSample={useSample} uploading={reports.uploading} />
      : <main className="rd-work" id="main-content">
        <div className="rd-stage-wrap"><PdfStage report={selected} focus={focus} onClearFocus={clearFocus} processing={processing} markedPages={markedPages} evidences={evidences}
          openKey={openCell} onOpenCell={openCellCard} onCloseCard={closeCellCard} selection={selection} onSelect={selectCells} renderCard={renderCard}
          checks={openChecks} onDismissCheck={dismissProblem} peekKey={peekKey} onPeek={setPeekKey}
          pick={swaps.pick} onPickHover={swaps.hover} onPickChoose={swaps.choose} onPickCancel={swaps.cancel} onAskSelection={selectionQuestionList.length ? askAboutSelection : null} askingSelection={askingSelection} onChartSelection={canChart ? drawChart : null} /></div>
        <aside className="rd-notes" aria-label="Câu trả lời">
          <div className="rd-notes-scroll" ref={notesRef}>
            {processing && <ReadingCard report={selected} />}
            {selected.extraction_status === "failed" && <FailedCard report={selected} onRetry={canReread ? (report) => reports.reextract(report).catch((error) => toast({ kind: "error", text: error.message })) : null} />}
            {ready && <BriefCard brief={brief.key === briefKey ? brief : { status: "loading" }} briefing={briefing} dismissed={problems.dismissed} onDismiss={dismissProblem} onRestore={problems.restore} activeKey={focus?.key} onFocus={focusOn} onAsk={ask} onRetry={() => loadBrief(briefKey, selected)} onOpenData={() => setDataOpen(true)} asked={askedQuestions} collapsed={conversation.notes.length > 0} scanned={briefing?.scanned} />}
            {conversation.notes.map((note) => <AnswerCard key={note.id} note={note} activeKey={focus?.key} onFocus={focusOn} onPeek={setPeekKey} onPick={swaps.start} pickBusy={Boolean(swaps.busy)} swap={swaps.swaps[note.id]}
              onUndoSwap={(id) => { swaps.undo(id); window.requestAnimationFrame(() => document.querySelector(`#note-${CSS.escape(id)} .rd-headline-value`)?.focus({ preventScroll: true })); }} onAsk={ask} onOpenData={() => setDataOpen(true)} onStop={stopAnswer} scanned={briefing?.scanned} onEdit={(text) => { setQuestion(text); askRef.current?.focus(); }} />)}
            {ready && charts.map((chart) => <ChartCard key={chart.id} chart={chart} evidences={evidences} loading={evidence.loading || !evidence.data} activeKey={openCell ?? focus?.key} onPeek={setPeekKey}
              onOpenCell={openFromChart} onShowCells={showChartCells}
              onChange={(id, patch) => changeCharts((list) => list.map((item) => (item.id === id ? { ...item, ...patch } : item)))} onRemove={removeChart} />)}
            {conversation.pending.map((item) => <PendingCard key={item.id} item={item} onRetry={(entry) => conversation.ask(entry.question, entry.id)} onDismiss={conversation.dismiss} />)}
          </div>
          <AskBox ref={askRef} value={question} onChange={setQuestion} onSubmit={ask} asking={conversation.asking} disabled={selected.extraction_status === "failed"} note={processing ? "Đang đọc báo cáo…" : undefined}
            suggestions={selectionSuggestions} suggestionsLabel="Gợi ý" />
        </aside>
      </main>}
    <DataPanel open={dataOpen} data={evidence.data} loading={evidence.loading} basePath={selected ? `/api/v1/sessions/${selected.sessionId}/documents/${selected.id}` : ""} onClose={() => setDataOpen(false)} onFocus={focusOn} onSaved={onEvidenceSaved} onReload={() => setRevision((value) => value + 1)} />
    {renaming && <RenameDialog report={renaming} onClose={() => setRenaming(null)} onSave={async (report, name) => { await reports.rename(report, name); toast({ text: "Đã đổi tên" }); }} />}
    <ConfirmDialog dialog={confirm} onClose={() => setConfirm(null)} />
    <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    <Toasts toasts={toasts} onClose={closeToast} />
    <DropOverlay onFile={upload} />
  </div>;
}
