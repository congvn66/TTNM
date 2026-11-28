import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { usePolling } from "./usePolling.js";

const SELECTED_KEY = "sourcelens-report-v2";
// Reports this tab uploaded or asked to read again: only their "ready" news is shown here.
const MINE_KEY = "sourcelens-my-uploads";
const MAX_BYTES = 100 * 1024 * 1024;
export const DEFAULT_PROJECT = "Báo cáo của tôi";
// The names the server gives an account's default project (config.DEFAULT_PROJECT_NAMES).
const DEFAULT_PROJECT_NAMES = [DEFAULT_PROJECT, "Workspace cá nhân"];
// How long an uploaded report is kept on screen while the list from the server does not show it yet.
const PENDING_MS = 120000;

function readStored(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function writeStored(key, value) {
  try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch { /* private window */ }
}
function readMine() {
  try { return new Set(JSON.parse(sessionStorage.getItem(MINE_KEY) || "[]")); } catch { return new Set(); }
}

/** The open report in the address (?r=…), so a reload or a copied link opens it again. */
function readUrl() {
  try { return new URLSearchParams(window.location.search).get("r"); } catch { return null; }
}
function writeUrl(id) {
  try {
    const params = new URLSearchParams(window.location.search);
    if (id) params.set("r", id); else params.delete("r");
    const query = params.toString();
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
  } catch { /* no history */ }
}

/** One report = one uploaded PDF. Sessions stay a backend detail. */
function flatten(sessions) {
  return sessions.flatMap((session) => (session.documents ?? []).map((document) => ({
    ...document,
    sessionId: session.id,
    sessionTitle: session.title,
  }))).sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
}

export function isProcessing(report) {
  return ["queued", "processing"].includes(report?.extraction_status);
}

/** Where an upload goes: the open report's project, else the default "Báo cáo của tôi", else the oldest. */
export function uploadSession(sessions, selected) {
  if (selected?.sessionId) return sessions.find((session) => session.id === selected.sessionId) ?? null;
  return sessions.find((session) => session.title === DEFAULT_PROJECT)
    ?? [...sessions].sort((a, b) => String(a.created_at ?? "").localeCompare(String(b.created_at ?? "")))[0] ?? null;
}

/**
 * The reports of the person using the app. `startGuest` is given when sign-in is in use:
 * then a visitor without a session has no reports, and the first upload makes them a guest.
 */
export function useReports({ user = null, startGuest = null, syncUrl = true } = {}) {
  const enabled = Boolean(user) || !startGuest;
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedIdState] = useState(() => {
    // The Library page still writes the older keys when it opens a report.
    const fromLibrary = readStored("sourcelens-active-document");
    if (fromLibrary) {
      writeStored("sourcelens-active-document", null); writeStored("sourcelens-active-session", null);
      writeStored(SELECTED_KEY, fromLibrary);
      return fromLibrary;
    }
    return (syncUrl && readUrl()) || readStored(SELECTED_KEY);
  });
  const [uploading, setUploading] = useState(null);
  // Uploaded here and not yet in the server's list: { id: { sessionId, document, at } }.
  const [pending, setPending] = useState({});
  // A report that was open and is gone (deleted elsewhere): its name, for one message.
  const [lost, setLost] = useState(null);
  const mine = useRef(readMine());
  const uploadingRef = useRef(null);
  uploadingRef.current = uploading;
  const loadSeq = useRef(0);
  const [loads, setLoads] = useState(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    const result = await request("/api/v1/sessions");
    let list = result.sessions ?? [];
    if (!list.length) {
      const created = await request("/api/v1/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: DEFAULT_PROJECT }) });
      list = [created.session];
    }
    if (seq === loadSeq.current) { setSessions(list); setLoads((count) => count + 1); }
    return list;
  }, []);

  useEffect(() => {
    if (!enabled) {
      // Signed out: drop the list and any request still on its way, so no report of the account stays on screen.
      loadSeq.current += 1;
      setSessions([]); setSelectedIdState(null); setLoading(false); setPending({});
      return;
    }
    // Becoming a guest during an upload reloads the list behind the upload, not over it.
    if (!uploadingRef.current) setLoading(true);
    load().then(() => setError("")).catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }, [load, enabled, user?.id]);

  // "Thử lại" after a failed first load: ask again without reloading the page.
  const retry = useCallback(() => {
    setLoading(true);
    return load().then(() => setError("")).catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }, [load]);

  const served = useMemo(() => flatten(sessions), [sessions]);
  // A fresh upload stays in the list even when a slow or busy server leaves it out of one reply.
  const reports = useMemo(() => {
    const now = Date.now();
    const extra = Object.values(pending).filter((item) => now - item.at < PENDING_MS && !served.some((report) => report.id === item.document.id))
      .map((item) => ({ ...item.document, sessionId: item.sessionId, sessionTitle: sessions.find((session) => session.id === item.sessionId)?.title ?? "" }));
    return extra.length ? [...extra, ...served] : served;
  }, [served, pending, sessions]);
  useEffect(() => {
    // Forget pending uploads the server now lists.
    if (Object.keys(pending).some((id) => served.some((report) => report.id === id))) {
      setPending((current) => Object.fromEntries(Object.entries(current).filter(([id]) => !served.some((report) => report.id === id))));
    }
  }, [served]);

  // The open report, kept for one more reply when the server leaves it out once.
  const lastSelected = useRef(null);
  const missing = useRef(0);
  const found = reports.find((report) => report.id === selectedId) ?? null;
  if (found) lastSelected.current = found;
  const selected = found ?? (selectedId && lastSelected.current?.id === selectedId && missing.current < 2 ? lastSelected.current : null);
  const anyProcessing = reports.some(isProcessing);

  // Poll only while something is being read.
  usePolling(anyProcessing, load, 2000);

  const select = useCallback((id) => {
    setSelectedIdState(id);
    writeStored(SELECTED_KEY, id);
    if (syncUrl) writeUrl(id);
  }, [syncUrl]);
  // Keep the address in step with the report on screen, from the first load on.
  useEffect(() => { if (!loading && syncUrl) writeUrl(selected?.id ?? null); }, [selected?.id, loading, syncUrl]);

  // The open report is not in the list: ask once more, then say so and go home.
  useEffect(() => {
    if (loading || !selectedId || found) { missing.current = 0; return undefined; }
    missing.current += 1;
    if (missing.current < 2) {
      const timer = window.setTimeout(() => load().catch(() => {}), 1500);
      return () => window.clearTimeout(timer);
    }
    setLost(lastSelected.current?.file_name ?? "");
    lastSelected.current = null;
    setSelectedIdState(null); writeStored(SELECTED_KEY, null); if (syncUrl) writeUrl(null);
    return undefined;
  }, [loads, loading, selectedId, Boolean(found)]);

  // An open report takes the upload into its own chat; from home it goes to the default project.
  const target = selected ? uploadSession(sessions, selected) : null;
  const uploadTarget = { sessionId: target?.id ?? null, title: target?.title ?? DEFAULT_PROJECT, many: sessions.length > 1 };

  const remember = useCallback((id) => {
    mine.current.add(id);
    try { sessionStorage.setItem(MINE_KEY, JSON.stringify([...mine.current].slice(-50))); } catch { /* storage blocked */ }
  }, []);
  const isMine = useCallback((id) => mine.current.has(id), []);

  const upload = useCallback(async (file) => {
    if (!file) return null;
    const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name ?? "");
    if (!isPdf) throw new Error("Chỉ nhận tệp PDF.");
    if (file.size > MAX_BYTES) throw new Error("Tệp lớn hơn 100 MB.");
    // Shown at once: sending a PDF to cloud storage takes a few seconds.
    setUploading({ name: file.name, size: file.size, startedAt: new Date().toISOString(), project: uploadTarget.many ? uploadTarget.title : "" });
    try {
      if (!enabled) await startGuest();
      const form = new FormData();
      form.append("file", file);
      let sessionId = enabled ? uploadTarget.sessionId : null;
      let result = null;
      if (!sessionId) {
        // Into the account's default project (the server picks its newest chat, or starts one).
        // A server without projects (local mode, older API) takes it into a chat as before.
        const projects = await request("/api/v1/projects").then((body) => body.projects ?? []).catch(() => []);
        const project = projects.find((item) => DEFAULT_PROJECT_NAMES.includes(item.name));
        if (project) {
          try { result = await request(`/api/v1/projects/${project.id}/documents`, { method: "POST", body: form }); } catch (failure) { if (![404, 405, 503].includes(failure.status)) throw failure; }
        }
        if (!result) sessionId = uploadSession(await load(), null)?.id;
      }
      if (!result) result = await request(`/api/v1/sessions/${sessionId}/documents`, { method: "POST", body: form });
      sessionId = result.session_id ?? sessionId;
      const document = result.document;
      // A list request sent before this upload finished would come back without it: its reply is dropped.
      loadSeq.current += 1;
      remember(document.id);
      // Shown from the pending list until the server's own list has it (not added to that list here,
      // or the first reply without it would count as "the server has it" and drop it).
      setPending((current) => ({ ...current, [document.id]: { sessionId, document, at: Date.now() } }));
      select(document.id);
      load().catch(() => {});
      return document;
    } finally {
      setUploading(null);
    }
  }, [uploadTarget.sessionId, uploadTarget.many, uploadTarget.title, load, select, enabled, startGuest, remember]);

  // Rename and delete show at once; the server's list follows.
  const patchDocument = useCallback((report, change) => {
    setSessions((current) => current.map((session) => session.id !== report.sessionId ? session : {
      ...session,
      documents: (session.documents ?? []).flatMap((item) => (item.id !== report.id ? [item] : change ? [{ ...item, ...change }] : [])),
    }));
    setPending((current) => { if (!current[report.id]) return current; const next = { ...current }; if (change) next[report.id] = { ...next[report.id], document: { ...next[report.id].document, ...change } }; else delete next[report.id]; return next; });
  }, []);

  const rename = useCallback(async (report, name) => {
    const fileName = name.trim();
    if (!fileName) return;
    await request(`/api/v1/sessions/${report.sessionId}/documents/${report.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_name: fileName }) });
    patchDocument(report, { file_name: fileName });
    load().catch(() => {});
  }, [load, patchDocument]);

  const remove = useCallback(async (report) => {
    await request(`/api/v1/sessions/${report.sessionId}/documents/${report.id}`, { method: "DELETE" });
    if (report.id === selectedId) { lastSelected.current = null; select(null); }
    patchDocument(report, null);
    load().catch(() => {});
  }, [load, select, selectedId, patchDocument]);

  const reextract = useCallback(async (report) => {
    const result = await request(`/api/v1/sessions/${report.sessionId}/documents/${report.id}/extraction`, { method: "POST" });
    remember(report.id);
    await load();
    return result;
  }, [load, remember]);

  return { reports, selected, select, loading, error, retry, reload: load, upload, uploading, uploadTarget, rename, remove, reextract, anyProcessing, lost, clearLost: () => setLost(null), isMine };
}
