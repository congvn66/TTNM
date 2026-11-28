import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { usePolling } from "./usePolling.js";

// Questions still being sent, so a reload can send them again (same key: the server answers once).
const ASKING_KEY = "sourcelens-asking-v1";
// Questions the server never took, kept so they stay in the list with "Thử lại" after a reload.
const FAILED_KEY = "sourcelens-failed-v1";
const FAILED_KEEP_MS = 24 * 60 * 60 * 1000;
const RESUME_WITHIN_MS = 10 * 60 * 1000;
// A question the server accepted should show up in the conversation; after this long without it, it was lost.
const LOST_AFTER_MS = 30_000;

function readList(storage, key) { try { return JSON.parse(storage().getItem(key) || "[]"); } catch { return []; } }
function writeList(storage, key, items) { try { if (items.length) storage().setItem(key, JSON.stringify(items)); else storage().removeItem(key); } catch { /* storage off */ } }
const session = () => sessionStorage;
const local = () => localStorage;
const readAsking = () => readList(session, ASKING_KEY);
const writeAsking = (items) => writeList(session, ASKING_KEY, items);

/** Failed questions of one report kept in this browser, newest last; old ones drop out. */
export function readFailed(reportId) {
  return readList(local, FAILED_KEY).filter((item) => item.reportId === reportId && Date.now() - item.at < FAILED_KEEP_MS);
}
function keepFailed(item) {
  const others = readList(local, FAILED_KEY).filter((entry) => entry.id !== item.id && Date.now() - entry.at < FAILED_KEEP_MS);
  writeList(local, FAILED_KEY, [...others, item].slice(-40));
}
function forgetFailed(id) { writeList(local, FAILED_KEY, readList(local, FAILED_KEY).filter((entry) => entry.id !== id)); }

function isWorking(message) {
  return message?.role === "assistant" && (message.status === "processing" || message.structured_answer?.presentation === "processing_v1");
}

const errorFields = (error) => ({ message: error.message, code: error.code, status: error.status, detail: error.detail });

/**
 * Stop the background job writing one answer. The job id comes with the
 * accepted question; without it the job is found by its answer's id.
 * A job that already finished cannot be stopped, which is not an error.
 */
export async function cancelAnswer(assistantId, jobId = null) {
  let id = jobId;
  if (!id) {
    const jobs = (await request("/api/v1/jobs")).jobs ?? [];
    id = jobs.find((job) => job.kind === "answer_question" && job.payload?.assistant_message_id === assistantId && ["queued", "running"].includes(job.status))?.id ?? null;
  }
  if (!id) return false;
  try {
    await request(`/api/v1/jobs/${id}/cancel`, { method: "POST" });
    return true;
  } catch (error) {
    if (error.code === "JOB_NOT_CANCELLABLE") return false;
    throw error;
  }
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

/**
 * Questions and answers about one report. Only the ask box waits while the AI answers.
 *
 * A question the client is still sending is a pending item:
 * "asking" (sending), "sent" (the server took it, not in the list yet),
 * "stopped" (the reader pressed Dừng) or "failed".
 */
export function useConversation(report) {
  const [messages, setMessages] = useState([]);
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadedId, setLoadedId] = useState(null);
  const reportRef = useRef(report);
  reportRef.current = report;
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  // Keys sent from this page: a reload's resume must not send them a second time.
  const sentHere = useRef(new Set());
  // Pending items the reader stopped while they were still being sent.
  const stopped = useRef(new Set());

  /** The report's messages, fresh from the server; null when another report was opened meanwhile. */
  const load = useCallback(async () => {
    const current = reportRef.current;
    if (!current) { setMessages([]); return null; }
    const detail = await request(`/api/v1/sessions/${current.sessionId}`);
    if (reportRef.current?.id !== current.id) return null;
    const list = (detail.session?.messages ?? []).filter((message) => message.document_id === current.id);
    setMessages(list);
    setLoadedId(current.id);
    return list;
  }, []);

  useEffect(() => {
    setMessages([]); setLoadedId(null);
    stopped.current.clear();
    // Questions that failed before stay in the list, with "Thử lại".
    setPending(report ? readFailed(report.id).map((item) => ({ ...item, status: "failed" })) : []);
    if (!report) return;
    setLoading(true);
    load().catch(() => {}).finally(() => setLoading(false));
  }, [report?.id, load]);

  // A pending item is done once its question or answer is in the list. One the server took but
  // never listed was lost (a failed save): it becomes a failed card, not a card that waits forever.
  useEffect(() => {
    const ids = new Set(messages.map((message) => message.id));
    setPending((items) => {
      let changed = false;
      const next = items.flatMap((item) => {
        if ((item.status === "sent" || item.status === "stopped") && (ids.has(item.assistantId) || ids.has(item.userId))) { changed = true; return []; }
        if (item.status === "sent" && loadedId && Date.now() - item.sentAt > LOST_AFTER_MS) {
          changed = true;
          const failed = { ...item, status: "failed", errorObject: { message: "", code: "QUESTION_LOST" } };
          if (reportRef.current) keepFailed(storedFailed(failed, reportRef.current.id));
          return [failed];
        }
        return [item];
      });
      return changed ? next : items;
    });
  }, [messages, loadedId]);

  const working = messages.some(isWorking) || pending.some((item) => item.status === "sent");
  usePolling(working, load, 1500);

  const update = (id, patch) => setPending((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));

  /** True when the server already holds this question (it may save it and still fail the request). */
  const landed = (list, question, before) => Boolean(list?.some((message) => message.role === "user" && !before.has(message.id) && message.body?.trim() === question));

  const ask = useCallback(async (questionText, retryOf = null, resumeKey = null) => {
    const question = questionText.trim();
    const current = reportRef.current;
    if (!question || !current) return null;
    const previous = retryOf ? pendingRef.current.find((item) => item.id === retryOf) : null;
    // The same key lets the server answer a resent question only once. A stopped question asked again is a new question.
    const key = resumeKey ?? (previous && previous.status !== "stopped" ? previous.key : null) ?? crypto.randomUUID();
    sentHere.current.add(key);
    writeAsking([...readAsking().filter((item) => item.key !== key), { key, reportId: current.id, question, at: Date.now() }]);
    if (retryOf) forgetFailed(retryOf);
    const localId = `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const before = new Set(messagesRef.current.map((message) => message.id));
    setPending((items) => [...items.filter((item) => item.id !== retryOf), { id: localId, key, question, startedAt: Date.now(), status: "asking" }]);
    try {
      const result = await request(`/api/v1/sessions/${current.sessionId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({ document_id: current.id, question }),
      });
      const assistantId = result?.assistant_message?.id ?? null;
      const userId = result?.user_message?.id ?? null;
      if (stopped.current.has(localId)) {
        // The reader pressed Dừng while this was being sent: stop the job the server just queued.
        update(localId, { assistantId, userId });
        if (assistantId && isWorking(result.assistant_message)) await cancelAnswer(assistantId, result.job?.id).catch(() => {});
        await load().catch(() => {});
        return null;
      }
      update(localId, { status: "sent", assistantId, userId, jobId: result?.job?.id ?? null, sentAt: Date.now() });
      await load().catch(() => {});
      return result?.assistant_message ?? null;
    } catch (error) {
      // The server may have saved the question and then failed (a 500 reads as a network error):
      // the list is the truth, so look there before calling it failed.
      const list = await load().catch(() => null);
      if (landed(list, question, before)) { setPending((items) => items.filter((item) => item.id !== localId)); return null; }
      if (stopped.current.has(localId)) return null;
      const fields = errorFields(error);
      // The list loaded, so the server is up: the request failed there, not on the network.
      // (client.js gives a failed fetch no code, only its CLIENT_ERRORS text.)
      if (list && !error.status && !error.code) fields.code = /phản hồi/.test(error.message) ? "CLIENT_TIMEOUT" : "SERVER_ERROR";
      const failed = { id: localId, key, question, startedAt: Date.now(), status: "failed", error: error.message, errorObject: fields };
      setPending((items) => items.map((item) => (item.id === localId ? failed : item)));
      keepFailed(storedFailed(failed, current.id));
      return null;
    } finally {
      writeAsking(readAsking().filter((item) => item.key !== key));
    }
  }, [load]);

  /** "Dừng" on a question still being sent, or sent but not listed yet. */
  const stop = useCallback(async (id) => {
    const item = pendingRef.current.find((entry) => entry.id === id);
    if (!item) return;
    stopped.current.add(id);
    update(id, { status: "stopped" });
    if (item.assistantId) {
      await cancelAnswer(item.assistantId, item.jobId).catch(() => {});
      await load().catch(() => {});
    }
  }, [load]);

  /** "Dừng" on an answer the worker is writing. True when a job was stopped. */
  const stopReply = useCallback(async (reply) => {
    const done = await cancelAnswer(reply.id);
    await load().catch(() => {});
    return done;
  }, [load]);

  const dismiss = useCallback((id) => { forgetFailed(id); setPending((items) => items.filter((item) => item.id !== id)); }, []);

  // A question still being sent when the page reloaded is sent again, with its own key.
  // Only questions from an earlier page: one sent from this page is still on its way (or done).
  const resumed = useRef(new Set());
  useEffect(() => {
    if (!report || loadedId !== report.id || resumed.current.has(report.id)) return;
    resumed.current.add(report.id);
    const asked = new Set(messages.filter((message) => message.role === "user").map((message) => message.body?.trim()));
    const mine = readAsking().filter((item) => item.reportId === report.id && !sentHere.current.has(item.key));
    writeAsking(readAsking().filter((item) => item.reportId !== report.id || sentHere.current.has(item.key)));
    mine.filter((item) => !asked.has(item.question) && Date.now() - (item.at ?? 0) < RESUME_WITHIN_MS).forEach((item) => ask(item.question, null, item.key));
  }, [report?.id, loadedId, messages, ask]);

  const notes = useMemo(() => pairNotes(messages), [messages]);
  // Each pending item carries its own stop, so the card needs nothing else to offer "Dừng".
  const shown = useMemo(() => pending.map((item) => (item.status === "asking" || item.status === "sent" ? { ...item, stop: () => stop(item.id) } : item)), [pending, stop]);
  const asking = pending.some((item) => item.status === "asking");
  return { notes, pending: shown, loading, loadedId, asking, ask, stop, stopReply, dismiss, reload: load };
}

function storedFailed(item, reportId) {
  return { id: item.id, key: item.key, reportId, question: item.question, error: item.error ?? "", errorObject: item.errorObject ?? null, at: Date.now() };
}
