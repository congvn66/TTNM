import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { useTheme } from "../theme/ThemeProvider.jsx";
import { AskBox } from "./AskBox.jsx";
import { ConfirmDialog, DropOverlay, HelpDialog, RenameDialog, Toasts, TopBar, Tour, TOUR_LENGTH } from "./Chrome.jsx";
import { DataPanel } from "./DataPanel.jsx";
import { Home, SAMPLE_URL } from "./Home.jsx";
import { AnswerCard, BriefCard, FailedCard, PendingCard, ReadingCard, showNumber } from "./Notes.jsx";
import { PdfStage } from "./PdfStage.jsx";
import { buildBriefing } from "./reportChecks.js";
import { setSoundEnabled, soundEnabled, unlockSound, useReadySignal } from "./signals.js";
import { isProcessing, useReports } from "./useReports.js";
import { useConversation } from "./useConversation.js";
import "./reader.css";

// No upfront tour: a one-line tip in the summary until the first tap on a number.
const TAPPED_KEY = "sourcelens-tapped-v1";
const hasTapped = () => { try { return localStorage.getItem(TAPPED_KEY) === "yes"; } catch { return true; } };

const EDIT_NOT_KEPT_REASONS = { NOT_IN_NEW_READING: "không còn trong lần đọc mới", LOCATION_CHANGED: "vị trí đã thay đổi" };

/** What a re-read did to the user's corrections and old answers (from the audit). */
export function rereadSummary(report) {
  const run = report.extraction_history?.at(-1);
  const kept = Array.isArray(run?.edits_carried_over) ? run.edits_carried_over : [];
  const lost = Array.isArray(run?.edits_not_carried_over) ? run.edits_not_carried_over : [];
  const parts = [];
  if (kept.length) parts.push(`giữ lại ${kept.length} số bạn đã sửa`);
  if (lost.length) {
    const counts = new Map();
    for (const item of lost) { const reason = EDIT_NOT_KEPT_REASONS[item.code] ?? "không khớp lần đọc mới"; counts.set(reason, (counts.get(reason) ?? 0) + 1); }
    parts.push([...counts].map(([reason, count]) => `${count} số không giữ được vì ${reason}`).join(", "));
  }
  const flagged = run?.affected_message_ids?.length ?? 0;
  return `Đã đọc lại ${report.file_name}: ${report.numeric_evidence_count ?? 0} số liệu${parts.length ? `, ${parts.join("; ")}` : ""}.${flagged ? ` ${flagged} câu trả lời cần hỏi lại.` : ""}`;
}

function firstDataSource(reply) {
  const item = (reply?.structured_answer?.evidence ?? []).find((evidence) => evidence.kind === "data" && evidence.page);
  return item ? { page: item.page, boxes: item.bbox ? [item.bbox] : [], label: item.label, value: showNumber(item.value ?? item.raw_text), key: item.evidence_key, unsure: Boolean(item.data_status && item.data_status !== "valid") } : null;
}

export default function ReaderApp({ user = null, onSignOut = null, onNavigate }) {
  const { preference, setPreference } = useTheme();
  const reports = useReports();
  const { selected } = reports;
  const conversation = useConversation(selected);
  const [focus, setFocus] = useState(null);
  const [question, setQuestion] = useState("");
  const [toasts, setToasts] = useState([]);
  const [helpOpen, setHelpOpen] = useState(false);
  const [tourStep, setTourStep] = useState(null);
  const [dataOpen, setDataOpen] = useState(false);
  const [evidence, setEvidence] = useState({ key: null, data: null, loading: false });
  const [revision, setRevision] = useState(0);
  const [sound, setSound] = useState(soundEnabled);
  const [renaming, setRenaming] = useState(null);
  const [confirm, setConfirm] = useState(null);
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

  const [tapped, setTapped] = useState(hasTapped);
  const focusOn = useCallback((next) => {
    setFocus(next?.page ? { ...next, nonce: Date.now() } : null);
    if (next?.page) { setTapped(true); try { localStorage.setItem(TAPPED_KEY, "yes"); } catch { /* private mode */ } }
    // On narrow screens the page sits above the notes: bring it into view.
    if (next?.page && window.matchMedia?.("(max-width: 1000px)").matches) document.querySelector(".rd-stage-wrap")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);
  const clearFocus = useCallback(() => setFocus(null), []);
  useEffect(() => { setFocus(null); setQuestion(""); setDataOpen(false); document.title = selected ? `${selected.file_name} · SourceLens` : "SourceLens"; }, [selected?.id]);

  useReadySignal(reports.reports, useCallback((event) => {
    const mine = event.report.id === selected?.id;
    if (event.kind === "ready" && (event.report.extraction_history?.length ?? 0) > 1) {
      toast({ kind: "ready", group: `report-${event.report.id}`, text: rereadSummary(event.report) });
    } else if (event.kind === "ready") {
      toast({ kind: "ready", group: `report-${event.report.id}`, text: mine ? `Đã đọc xong ${event.report.file_name}. Hỏi thử một câu nhé!` : `Đã đọc xong ${event.report.file_name}.`, action: mine ? null : { label: "Mở", onClick: () => reports.select(event.report.id) } });
      if (mine) window.setTimeout(() => askRef.current?.focus(), 300);
    } else {
      toast({ kind: "error", group: `report-${event.report.id}`, text: `Chưa đọc được ${event.report.file_name}.` });
    }
  }, [selected?.id, toast, reports]));

  // One fetch of the numbers feeds both the briefing and the data panel.
  const ready = selected?.extraction_status === "ready";
  // A re-read changes the numbers, so its result count is part of the key.
  const evidenceKey = ready ? `${selected.id}:${revision}:${selected.numeric_evidence_count ?? ""}:${selected.extraction_history?.length ?? 0}` : null;
  useEffect(() => {
    if (!evidenceKey || evidence.key === evidenceKey) return;
    let live = true;
    setEvidence({ key: evidenceKey, data: null, loading: true });
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
      if (!answer) throw new Error("Máy chủ chưa trả về bản tóm tắt.");
      setBrief((current) => current.key === key ? { key, status: "ready", answer } : current);
    } catch (error) {
      setBrief((current) => current.key === key ? { key, status: error.code === "BRIEF_UNAVAILABLE" ? "unavailable" : "error", error: { message: error.message, code: error.code, status: error.status, detail: error.detail } } : current);
    }
  }, []);
  useEffect(() => { if (briefKey && brief.key !== briefKey) loadBrief(briefKey, selected); }, [briefKey]);

  const briefing = useMemo(() => evidence.data && evidence.key === evidenceKey ? buildBriefing(evidence.data.evidences ?? []) : null, [evidence, evidenceKey]);

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
    window.requestAnimationFrame(() => { const node = notesRef.current; const card = node?.querySelector(".rd-qa:last-of-type"); if (node && card) node.scrollTo({ top: card.offsetTop - 12, behavior: "smooth" }); });
    const source = firstDataSource(fresh.at(-1));
    if (source) focusOn(source); else setFocus(null);
  }, [conversation.notes, conversation.loadedId, selected, focusOn]);

  // Opening a report shows the top; asking scrolls to the newest card.
  useEffect(() => { notesRef.current?.scrollTo({ top: 0 }); }, [selected?.id]);
  useEffect(() => {
    const node = notesRef.current;
    if (node && conversation.pending.length) node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [conversation.pending.length]);

  const closeTour = () => setTourStep(null);

  const upload = useCallback(async (file) => {
    if (!file) return;
    unlockSound();
    try {
      const document = await reports.upload(file);
      if (document) toast({ group: `report-${document.id}`, text: `Đã tải lên ${document.file_name}. Đang đọc, xong sẽ có tiếng chuông.` });
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
      toast({ kind: "error", text: `Không mở được báo cáo mẫu. ${error.message}` });
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
    toast({ text: affected ? `Đã lưu số mới. ${affected} câu trả lời dùng số cũ cần hỏi lại.` : "Đã lưu số mới." });
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
      toast({ text: job ? "Đã dừng trả lời." : "Câu trả lời vừa xong, không cần dừng." });
    } catch (error) {
      toast({ kind: "error", text: error.message });
    }
  }, [conversation, toast]);

  // The Library page sends people here with ?upload=1 to add a report.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("upload") !== "1") return;
    params.delete("upload");
    window.history.replaceState({}, "", `${window.location.pathname}${params.toString() ? `?${params}` : ""}`);
    window.setTimeout(() => uploadRef.current?.click(), 100);
  }, []);

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
    text: "SourceLens sẽ đọc lại từ đầu, mất khoảng nửa phút. Số bạn đã sửa được giữ nếu vẫn ở đúng chỗ; câu trả lời cũ dùng số thay đổi sẽ cần hỏi lại.",
    confirmLabel: "Đọc lại",
    onConfirm: () => reports.reextract(selected).then(() => toast({ group: `report-${selected.id}`, text: "Đang đọc lại báo cáo. Xong sẽ có tiếng chuông." })).catch((error) => toast({ kind: "error", text: error.message })),
  });
  const confirmDelete = (report) => setConfirm({
    title: `Xoá ${report.file_name}?`,
    text: "Báo cáo và các câu hỏi về nó sẽ không còn trong danh sách của bạn.",
    confirmLabel: "Xoá báo cáo",
    danger: true,
    onConfirm: () => reports.remove(report).then(() => toast({ text: `Đã xoá ${report.file_name}.` })).catch((error) => toast({ kind: "error", text: error.message })),
  });
  const menuItems = [
    selected && { section: "Báo cáo này" },
    selected && { label: "Số liệu đã đọc", hint: "Xem và sửa các con số", onClick: () => setDataOpen(true), disabled: !ready },
    selected && { label: "Đổi tên", onClick: () => setRenaming(selected) },
    selected && canReread && { label: "Đọc lại", hint: "Khi nhiều số bị đọc sai", onClick: confirmReread },
    selected && { label: "Xoá báo cáo", danger: true, onClick: () => confirmDelete(selected) },
    { section: "Ứng dụng" },
    { label: "Giao diện", choices: [{ value: "light", label: "Sáng" }, { value: "dark", label: "Tối" }, { value: "system", label: "Theo máy" }].map((choice) => ({ ...choice, active: preference === choice.value })), onPick: setPreference },
    { label: `Âm báo khi đọc xong: ${sound ? "bật" : "tắt"}`, onClick: () => { setSoundEnabled(!sound); setSound(!sound); } },
    ready && { label: "Hướng dẫn từng bước", onClick: () => setTourStep(0) },
    user && onNavigate && { label: "Thư viện tài liệu", hint: "Sắp xếp báo cáo theo thư mục", onClick: () => onNavigate("/app/library") },
    user && onNavigate && { label: "Tài khoản", onClick: () => onNavigate("/app/settings/profile") },
    onSignOut && { label: "Đăng xuất", onClick: onSignOut },
  ];

  const askedQuestions = useMemo(() => new Set([...conversation.notes.map((note) => note.question?.body?.trim()), ...conversation.pending.map((item) => item.question.trim())].filter(Boolean)), [conversation.notes, conversation.pending]);

  const markedPages = useMemo(() => {
    const pages = new Set();
    conversation.notes.forEach((note) => (note.reply?.structured_answer?.evidence ?? []).forEach((item) => item.page && pages.add(item.page)));
    briefing?.checks.filter((check) => !check.ok).forEach((check) => pages.add(check.chip.page));
    return pages;
  }, [conversation.notes, briefing]);

  if (reports.loading) return <div className="rd-app"><div className="rd-boot" role="status"><span className="rd-spinner large" aria-hidden="true" />Đang mở SourceLens…</div></div>;
  if (reports.error && !reports.reports.length) return <div className="rd-app"><div className="rd-boot" role="alert"><h1>Chưa kết nối được máy chủ</h1><p>Kiểm tra mạng hoặc thử lại sau ít phút.</p><button type="button" className="rd-button primary" onClick={() => window.location.reload()}>Thử lại</button></div></div>;

  const processing = isProcessing(selected);
  return <div className="rd-app">
    <a className="rd-skip" href="#main-content">Bỏ qua điều hướng</a>
    <TopBar reports={reports.reports} selected={selected} onHome={() => reports.select(null)} onOpen={reports.select} onNew={() => uploadRef.current?.click()} onHelp={() => setHelpOpen(true)} menuItems={menuItems} />
    <input ref={uploadRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => { upload(event.target.files?.[0]); event.target.value = ""; }} />
    {!selected
      ? <Home reports={reports.reports} onOpen={reports.select} onFile={upload} onSample={useSample} uploading={reports.uploading} onDelete={confirmDelete} />
      : <main className="rd-work" id="main-content">
        <div className="rd-stage-wrap" data-tour="page"><PdfStage report={selected} focus={focus} onClearFocus={clearFocus} processing={processing} markedPages={markedPages} evidences={evidence.data?.evidences} /></div>
        <aside className="rd-notes" aria-label="Ghi chú và câu trả lời">
          <div className="rd-notes-scroll" ref={notesRef}>
            {processing && <ReadingCard report={selected} />}
            {selected.extraction_status === "failed" && <FailedCard report={selected} onRetry={canReread ? (report) => reports.reextract(report).catch((error) => toast({ kind: "error", text: error.message })) : null} />}
            {ready && <BriefCard brief={brief.key === briefKey ? brief : { status: "loading" }} briefing={briefing} activeKey={focus?.key} onFocus={focusOn} onAsk={ask} onRetry={() => loadBrief(briefKey, selected)} onOpenData={() => setDataOpen(true)} asked={askedQuestions} collapsed={conversation.notes.length > 0} scanned={briefing?.scanned} hint={!tapped} />}
            {conversation.notes.map((note) => <AnswerCard key={note.id} note={note} activeKey={focus?.key} onFocus={focusOn} onAsk={ask} onOpenData={() => setDataOpen(true)} onStop={stopAnswer} scanned={briefing?.scanned} onEdit={(text) => { setQuestion(text); askRef.current?.focus(); }} />)}
            {conversation.pending.map((item) => <PendingCard key={item.id} item={item} onRetry={(entry) => conversation.ask(entry.question, entry.id)} onDismiss={conversation.dismiss} />)}
          </div>
          <AskBox ref={askRef} value={question} onChange={setQuestion} onSubmit={ask} asking={conversation.asking} disabled={selected.extraction_status === "failed"} note={processing ? "Đang đọc báo cáo. Câu hỏi sẽ được trả lời khi đọc xong." : undefined} examples={(briefing?.suggestions ?? []).filter((item) => !askedQuestions.has(item.trim()))} />
        </aside>
      </main>}
    <DataPanel open={dataOpen} data={evidence.data} loading={evidence.loading} basePath={selected ? `/api/v1/sessions/${selected.sessionId}/documents/${selected.id}` : ""} onClose={() => setDataOpen(false)} onFocus={focusOn} onSaved={onEvidenceSaved} onReload={() => setRevision((value) => value + 1)} />
    {renaming && <RenameDialog report={renaming} onClose={() => setRenaming(null)} onSave={async (report, name) => { await reports.rename(report, name); toast({ text: `Đã đổi tên thành ${name}.` }); }} />}
    <ConfirmDialog dialog={confirm} onClose={() => setConfirm(null)} />
    <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} onTour={() => setTourStep(0)} canTour={ready} />
    {tourStep !== null && tourStep < TOUR_LENGTH && ready && <Tour step={tourStep} onNext={() => setTourStep((step) => step + 1)} onClose={closeTour} onFinish={() => { closeTour(); window.setTimeout(() => askRef.current?.focus(), 50); }} />}
    <Toasts toasts={toasts} onClose={closeToast} />
    <DropOverlay onFile={upload} />
  </div>;
}
