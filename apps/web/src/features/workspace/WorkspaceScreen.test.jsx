/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ API: "http://localhost:8000", request: requestMock }));
vi.mock("pdfjs-dist", () => ({ GlobalWorkerOptions: {}, getDocument: () => ({ promise: Promise.reject(new Error("preview unavailable in test")), destroy: vi.fn() }) }));
import WorkspaceScreen from "./WorkspaceScreen.jsx";
import { ThemeProvider } from "../theme/ThemeProvider.jsx";

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  Element.prototype.scrollTo = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, arrayBuffer: async () => new ArrayBuffer(1) }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); requestMock.mockReset(); });

it("places replies after their linked questions even when the server returns them out of order", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [
    { id: "a2", role: "assistant", document_id: "doc", reply_to_message_id: "q2", body: "Answer two" },
    { id: "q1", role: "user", document_id: "doc", body: "Question one" },
    { id: "a1", role: "assistant", document_id: "doc", reply_to_message_id: "q1", body: "Answer one" },
    { id: "q2", role: "user", document_id: "doc", body: "Question two" },
  ] };
  requestMock.mockImplementation(async (path) => path === "/api/v1/sessions" ? { sessions: [{ ...session, messages: [] }] } : path === "/api/v1/sessions/chat" ? { session } : { jobs: [] });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("Answer two");
  expect([...view.container.querySelectorAll(".chat-body article p")].map((node) => node.textContent)).toEqual(["Question one", "Answer one", "Question two", "Answer two"]);
});

it("loads chat from session detail when the list contains metadata only", async () => {
  const rows = ["one", "two"].map((id) => ({ id, title: `Session ${id}`, documents: [], messages: [] }));
  requestMock.mockImplementation(async (path) => {
    if (path === "/api/v1/sessions") return { sessions: rows };
    if (path.startsWith("/api/v1/sessions/")) {
      const row = rows.find((s) => path.endsWith(s.id));
      return { session: { ...row, messages: [{ id: `msg-${row.id}`, role: "assistant", body: `History ${row.id}`, status: "completed" }] } };
    }
    return { jobs: [] };
  });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("History one");
  fireEvent.click(view.container.querySelectorAll(".session-button")[1]);
  await screen.findByText("History two");
  expect(screen.queryByText("History one")).toBeNull();
});

it("keeps an accepted question and polls its answer instead of resetting chat", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [] };
  let accepted = false;
  let detailReads = 0;
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions") return { sessions: [{ ...session, messages: [] }] };
    if (path.endsWith("/messages") && options?.method === "POST") {
      accepted = true;
      return { status: "queued", user_message: { id: "user", role: "user", document_id: "doc", body: "Summarize" }, assistant_message: { id: "answer", role: "assistant", document_id: "doc", status: "processing", body: "Waiting" } };
    }
    if (path === "/api/v1/sessions/chat") {
      if (accepted) detailReads++;
      return { session: { ...session, messages: accepted ? [
        { id: "user", role: "user", document_id: "doc", body: "Summarize" },
        { id: "answer", role: "assistant", document_id: "doc", status: detailReads > 1 ? "completed" : "processing", body: detailReads > 1 ? "Final answer" : "Waiting" },
      ] : [] } };
    }
    return { jobs: [] };
  });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  const composer = view.container.querySelector('[aria-label="Câu hỏi về tài liệu"]');
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: "Summarize" } });
  fireEvent.click(view.container.querySelector(".chat-composer button"));
  await screen.findByText("Final answer", {}, { timeout: 5000 });
  expect(screen.getByText("Summarize")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Xem luồng dữ liệu" })).toBeNull();
  const turns = [...view.container.querySelectorAll(".chat-body article")];
  expect(turns.map((turn) => turn.classList.contains("user") ? "user" : "assistant")).toEqual(["user", "assistant"]);
});

it("accepts a question while document extraction is still running", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "processing" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [] };
  let accepted = false;
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions") return { sessions: [{ ...session, messages: [] }] };
    if (path.endsWith("/messages") && options?.method === "POST") {
      accepted = true;
      return { status: "queued", user_message: { id: "user", role: "user", document_id: "doc", body: "Summarize" }, assistant_message: { id: "answer", role: "assistant", document_id: "doc", status: "processing", body: "Accepted" } };
    }
    if (path === "/api/v1/sessions/chat") return { session: { ...session, messages: accepted ? [
      { id: "user", role: "user", document_id: "doc", body: "Summarize" },
      { id: "answer", role: "assistant", document_id: "doc", status: "processing", body: "Accepted" },
    ] : [] } };
    return { jobs: [] };
  });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  const composer = view.container.querySelector('[aria-label="Câu hỏi về tài liệu"]');
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: "Summarize" } });
  const send = view.container.querySelector(".chat-composer button");
  expect(send.disabled).toBe(false);
  fireEvent.keyDown(composer, { key: "Enter", shiftKey: false });
  await screen.findByText("Summarize");
  expect(requestMock).toHaveBeenCalledWith("/api/v1/sessions/chat/messages", expect.objectContaining({ method: "POST" }));
});

it("keeps a failed question visible and lets the user retry it", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [] };
  let attempts = 0;
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions") return { sessions: [{ ...session, messages: [] }] };
    if (path === "/api/v1/sessions/chat") return { session: { ...session, messages: attempts > 1 ? [
      { id: "user", role: "user", document_id: "doc", body: "Summarize" },
      { id: "answer", role: "assistant", document_id: "doc", status: "completed", body: "Recovered answer" },
    ] : [] } };
    if (path.endsWith("/messages") && options?.method === "POST") {
      attempts++;
      if (attempts === 1) throw new Error("AI provider unavailable");
      return { status: "queued", user_message: { id: "user", role: "user", document_id: "doc", body: "Summarize" }, assistant_message: { id: "answer", role: "assistant", document_id: "doc", status: "completed", body: "Recovered answer" } };
    }
    return { jobs: [] };
  });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  const composer = view.container.querySelector('[aria-label="Câu hỏi về tài liệu"]');
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: "Summarize" } });
  fireEvent.keyDown(composer, { key: "Enter", shiftKey: false });
  await screen.findAllByText("AI provider unavailable");
  expect(screen.getByText("Summarize")).toBeTruthy();
  fireEvent.click(view.container.querySelector(".message.assistant .retry-answer-button"));
  await screen.findByText("Recovered answer");
  expect(attempts).toBe(2);
  expect(screen.getAllByText("Summarize")).toHaveLength(1);
});

it("shows tools-mode evidence and the executed script, without duplicate citation buttons", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const bbox = [0.1, 0.1, 0.2, 0.2];
  const session = { id: "chat", title: "My session", documents: [doc], messages: [
    { id: "q", role: "user", document_id: "doc", body: "Mức tăng?" },
    { id: "a", role: "assistant", document_id: "doc", reply_to_message_id: "q", mode: "ai:gemini", body: "760.25", citations: [{ page: 1, bbox }], structured_answer: {
      presentation: "document_assistant", answer: "Mức tăng là 760.25", sections: [], tables: [], claims: [], warnings: [],
      evidence: [
        { kind: "text", page: 1, quote: "Q2 2,010.75", bbox },
        { kind: "data", page: 1, evidence_key: "k2", label: "Q2 · Doanh thu", value: "2010.75", raw_text: "2,010.75", method_label: "đọc từ ô bảng", data_status: "valid", bbox },
      ],
      formulas: [{ name: "Python", expression: "result = value('k2') - value('k1')", substitution: "Q2 trừ Q1", result: "760.25", inputs: [{ evidence_key: "k2", label: "Q2 · Doanh thu", value: "2010.75", page: 1, bbox }] }],
    } },
  ] };
  requestMock.mockImplementation(async (path) => path === "/api/v1/sessions" ? { sessions: [{ ...session, messages: [] }] } : path === "/api/v1/sessions/chat" ? { session } : { jobs: [] });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("Mức tăng là 760.25");
  expect(view.container.querySelectorAll(".evidence-item")).toHaveLength(2);
  expect(screen.getByText("Script Python")).toBeTruthy();
  expect(screen.getByText("Kết quả: 760.25")).toBeTruthy();
  expect(screen.queryByText(/vùng trích dẫn/)).toBeNull();
});
