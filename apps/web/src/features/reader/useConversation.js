import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";

const ASKING_KEY = "sourcelens-asking-v1";
function readAsking() { try { return JSON.parse(sessionStorage.getItem(ASKING_KEY) || "[]"); } catch { return []; } }
function writeAsking(items) { try { if (items.length) sessionStorage.setItem(ASKING_KEY, JSON.stringify(items)); else sessionStorage.removeItem(ASKING_KEY); } catch { /* storage off */ } }

function isWorking(message) {
  return message?.role === "assistant" && (message.status === "processing" || message.structured_answer?.presentation === "processing_v1");
}

/**
 * Pair each question with its reply, in time order. A reply that names its
 * question goes there; a reply that does not (the JSON backend sends no link)
 * belongs to the latest question before it.
 */
export function pairNotes(messages) {
  const byId = new Map(messages.filter((message) => message.role === "user").map((message) => [message.id, { id: message.id, question: message, reply: null }]));
  const notes = [];
  let lastQuestion = null;
  for (const message of messages) {
    if (message.role === "user") {
      lastQuestion = byId.get(message.id);
      notes.push(lastQuestion);
    } else if (message.role === "assistant") {
      const target = message.reply_to_message_id ? byId.get(message.reply_to_message_id) : lastQuestion;
      if (target && !target.reply) target.reply = message;
      else notes.push({ id: message.id, question: null, reply: message });
    }
  }
  return notes;
}

/** Questions and answers about one report. Only the ask box waits while the AI answers. */
export function useConversation(report) {
  const [messages, setMessages] = useState([]);
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [loadedId, setLoadedId] = useState(null);
  const reportRef = useRef(report);
  reportRef.current = report;

  const load = useCallback(async () => {
    const current = reportRef.current;
    if (!current) { setMessages([]); return; }
    const detail = await request(`/api/v1/sessions/${current.sessionId}`);
    if (reportRef.current?.id !== current.id) return;
    setMessages((detail.session?.messages ?? []).filter((message) => message.document_id === current.id));
    setLoadedId(current.id);
  }, []);

  useEffect(() => {
    setMessages([]); setPending([]); setLoadedId(null);
    if (!report) return;
    setLoading(true);
    load().catch(() => {}).finally(() => setLoading(false));
  }, [report?.id, load]);

  const working = messages.some(isWorking);
  useEffect(() => {
    if (!working) return undefined;
    const timer = window.setInterval(() => { load().catch(() => {}); }, 1500);
    return () => window.clearInterval(timer);
  }, [working, load]);

  const ask = useCallback(async (questionText, retryOf = null, resumeKey = null) => {
    const question = questionText.trim();
    const current = reportRef.current;
    if (!question || !current) return;
    // The same key lets the server answer a resent question only once.
    const key = resumeKey ?? crypto.randomUUID();
    writeAsking([...readAsking().filter((item) => item.key !== key), { key, reportId: current.id, question, at: Date.now() }]);
    const localId = `local-${Date.now()}`;
    const startedAt = Date.now();
    setPending((items) => [...items.filter((item) => item.id !== retryOf), { id: localId, question, startedAt, status: "asking" }]);
    setAsking(true);
    try {
      const result = await request(`/api/v1/sessions/${current.sessionId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({ document_id: current.id, question }),
      });
      await load().catch(() => {});
      setPending((items) => items.filter((item) => item.id !== localId));
      return result.assistant_message;
    } catch (error) {
      setPending((items) => items.map((item) => item.id === localId ? { ...item, status: "failed", error: error.message, errorObject: { message: error.message, code: error.code, status: error.status, detail: error.detail } } : item));
      return null;
    } finally {
      writeAsking(readAsking().filter((item) => item.key !== key));
      setAsking(false);
    }
  }, [load]);

  const dismiss = useCallback((id) => setPending((items) => items.filter((item) => item.id !== id)), []);

  // A question still being answered when the page reloaded is sent again.
  const resumed = useRef(new Set());
  useEffect(() => {
    if (!report || loadedId !== report.id || resumed.current.has(report.id)) return;
    resumed.current.add(report.id);
    const asked = new Set(messages.filter((message) => message.role === "user").map((message) => message.body?.trim()));
    const waiting = readAsking().filter((item) => item.reportId === report.id);
    writeAsking(readAsking().filter((item) => item.reportId !== report.id));
    waiting.filter((item) => !asked.has(item.question)).forEach((item) => ask(item.question, null, item.key));
  }, [report?.id, loadedId, messages, ask]);

  const notes = useMemo(() => pairNotes(messages), [messages]);
  return { notes, pending, loading, loadedId, asking, ask, dismiss, reload: load };
}
