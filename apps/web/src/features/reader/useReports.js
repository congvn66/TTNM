import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { usePolling } from "./usePolling.js";

const SELECTED_KEY = "sourcelens-report-v2";
const MAX_BYTES = 100 * 1024 * 1024;

function readStored(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function writeStored(key, value) {
  try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch { /* private window */ }
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

/**
 * The reports of the person using the app. `startGuest` is given when sign-in is in use:
 * then a visitor without a session has no reports, and the first upload makes them a guest.
 */
export function useReports({ user = null, startGuest = null } = {}) {
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
    return readStored(SELECTED_KEY);
  });
  const [uploading, setUploading] = useState(null);
  const uploadingRef = useRef(null);
  uploadingRef.current = uploading;
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    const result = await request("/api/v1/sessions");
    let list = result.sessions ?? [];
    if (!list.length) {
      const created = await request("/api/v1/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "Báo cáo của tôi" }) });
      list = [created.session];
    }
    if (seq === loadSeq.current) setSessions(list);
    return list;
  }, []);

  useEffect(() => {
    if (!enabled) {
      // Signed out: drop the list and any request still on its way, so no report of the account stays on screen.
      loadSeq.current += 1;
      setSessions([]); setSelectedIdState(null); setLoading(false);
      return;
    }
    // Becoming a guest during an upload reloads the list behind the upload card, not over it.
    if (!uploadingRef.current) setLoading(true);
    load().then(() => setError("")).catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }, [load, enabled, user?.id]);

  const reports = useMemo(() => flatten(sessions), [sessions]);
  const selected = reports.find((report) => report.id === selectedId) ?? null;
  const anyProcessing = reports.some(isProcessing);

  // Poll only while something is being read.
  usePolling(anyProcessing, load, 2000);

  const select = useCallback((id) => {
    setSelectedIdState(id);
    writeStored(SELECTED_KEY, id);
  }, []);

  const uploadSessionId = selected?.sessionId ?? sessions[0]?.id ?? null;

  const upload = useCallback(async (file) => {
    if (!file) return null;
    const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name ?? "");
    if (!isPdf) throw new Error("Chỉ nhận tệp PDF.");
    if (file.size > MAX_BYTES) throw new Error("Tệp lớn hơn 100 MB.");
    // Shown at once: sending a PDF to cloud storage takes a few seconds.
    setUploading({ name: file.name, size: file.size, startedAt: new Date().toISOString() });
    try {
      if (!enabled) await startGuest();
      let sessionId = enabled ? uploadSessionId : null;
      if (!sessionId) sessionId = (await load())[0]?.id;
      const form = new FormData();
      form.append("file", file);
      const result = await request(`/api/v1/sessions/${sessionId}/documents`, { method: "POST", body: form });
      const document = result.document;
      setSessions((current) => current.map((session) => session.id !== sessionId ? session : { ...session, documents: [...(session.documents ?? []).filter((item) => item.id !== document.id), document] }));
      select(document.id);
      load().catch(() => {});
      return document;
    } finally {
      setUploading(null);
    }
  }, [uploadSessionId, load, select, enabled, startGuest]);

  const rename = useCallback(async (report, name) => {
    const fileName = name.trim();
    if (!fileName) return;
    await request(`/api/v1/sessions/${report.sessionId}/documents/${report.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_name: fileName }) });
    await load();
  }, [load]);

  const remove = useCallback(async (report) => {
    await request(`/api/v1/sessions/${report.sessionId}/documents/${report.id}`, { method: "DELETE" });
    if (report.id === selectedId) select(null);
    await load();
  }, [load, select, selectedId]);

  const reextract = useCallback(async (report) => {
    const result = await request(`/api/v1/sessions/${report.sessionId}/documents/${report.id}/extraction`, { method: "POST" });
    await load();
    return result;
  }, [load]);

  return { reports, selected, select, loading, error, reload: load, upload, uploading, rename, remove, reextract, anyProcessing };
}
