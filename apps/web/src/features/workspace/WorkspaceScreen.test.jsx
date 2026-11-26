/** @vitest-environment jsdom */
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", async (importActual) => ({ ...await importActual(), API: "http://localhost:8000", request: requestMock }));
const { pdfFailure } = vi.hoisted(() => ({ pdfFailure: { current: null } }));
vi.mock("pdfjs-dist", () => ({ GlobalWorkerOptions: {}, getDocument: () => ({ promise: Promise.reject(pdfFailure.current ?? new Error("preview unavailable in test")), destroy: vi.fn() }) }));
import WorkspaceScreen from "./WorkspaceScreen.jsx";
import { ThemeProvider } from "../theme/ThemeProvider.jsx";

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  Element.prototype.scrollTo = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, arrayBuffer: async () => new ArrayBuffer(1) }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); requestMock.mockReset(); pdfFailure.current = null; });

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

it("creates one first session when several refreshes find none", async () => {
  // A tab that still holds an old session list refreshes on mount and again
  // for its remembered session; StrictMode runs both effects twice.
  sessionStorage.setItem("sourcelens-session-snapshot-v1", JSON.stringify({ savedAt: Date.now(), sessions: [{ id: "old", title: "Old", documents: [], messages: [] }] }));
  localStorage.setItem("sourcelens-active-session", "old");
  const created = [];
  requestMock.mockImplementation(async (path, options) => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    if (path === "/api/v1/sessions" && options?.method === "POST") {
      const session = { id: `new-${created.length + 1}`, title: "Phiên phân tích đầu tiên", documents: [], messages: [] };
      created.push(session);
      return { session };
    }
    if (path === "/api/v1/sessions") return { sessions: [...created] };
    if (path.startsWith("/api/v1/sessions/")) return { session: created.find((session) => path.endsWith(session.id)) ?? created[0] };
    return { jobs: [] };
  });
  render(<StrictMode><ThemeProvider><WorkspaceScreen /></ThemeProvider></StrictMode>);
  await screen.findByText("Phiên phân tích đầu tiên");
  await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
  expect(created).toHaveLength(1);
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
  expect(screen.getByText("Phép tính")).toBeTruthy();
  expect(screen.getByText("Kết quả: 760,25")).toBeTruthy();
  expect(screen.queryByText(/vùng trích dẫn/)).toBeNull();
});

it.each([["available", true], ["unsupported", false]])("offers re-extraction only where the backend supports it (%s)", async (reextraction, offered) => {
  const doc = { id: "doc", file_name: "Broken.pdf", byte_size: 100, extraction_status: "failed" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [{ id: "a", role: "assistant", document_id: "doc", body: "Ready" }] };
  requestMock.mockImplementation(async (path) => path === "/health" ? { capabilities: { reextraction: { status: reextraction } } } : path === "/api/v1/sessions" ? { sessions: [{ ...session, messages: [] }] } : path === "/api/v1/sessions/chat" ? { session } : path.endsWith("/extraction") ? { affected_message_ids: [] } : { jobs: [] });
  render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("Ready");
  if (!offered) { expect(screen.queryByText("Trích xuất lại")).toBeNull(); return; }
  fireEvent.click(await screen.findByText("Trích xuất lại"));
  expect(requestMock).not.toHaveBeenCalledWith("/api/v1/sessions/chat/documents/doc/extraction", { method: "POST" });
  fireEvent.click(await screen.findByRole("button", { name: "Đọc lại tài liệu" }));
  await waitFor(() => expect(requestMock).toHaveBeenCalledWith("/api/v1/sessions/chat/documents/doc/extraction", { method: "POST" }));
});

it("asks before re-reading a document and shows why the server refused", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [] };
  requestMock.mockImplementation(async (path) => {
    if (path === "/health") return { capabilities: { reextraction: { status: "available" } } };
    if (path === "/api/v1/sessions") return { sessions: [session] };
    if (path === "/api/v1/sessions/chat") return { session };
    if (path.endsWith("/extraction")) throw Object.assign(new Error("Chưa hỗ trợ trích xuất lại khi lưu bằng PostgreSQL; hãy tải lại PDF."), { status: 409, code: "REEXTRACTION_NOT_SUPPORTED" });
    return { jobs: [] };
  });
  render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  fireEvent.click(await screen.findByText("Trích xuất lại"));
  const dialog = await screen.findByRole("dialog", { name: "Đọc lại tài liệu này?" });
  expect(dialog.textContent).toContain("chỉ được giữ khi số đó vẫn ở cùng vị trí");
  fireEvent.click(screen.getByRole("button", { name: "Đọc lại tài liệu" }));
  const alert = await screen.findByText("Chưa hỗ trợ trích xuất lại khi lưu bằng PostgreSQL; hãy tải lại PDF.");
  expect(alert.getAttribute("role")).toBe("alert");
  expect(screen.getByRole("dialog", { name: "Đọc lại tài liệu này?" })).toBeTruthy();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "Đọc lại tài liệu này?" })).toBeNull();
});

it("closes confirmation notices by itself but keeps errors until closed", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const session = { id: "chat", title: "My session", documents: [], messages: [] };
    let creates = 0;
    requestMock.mockImplementation(async (path, options) => {
      if (path === "/api/v1/sessions" && options?.method === "POST") {
        creates++;
        if (creates > 1) throw new Error("Không thể tạo phiên.");
        return { session: { id: "new", title: "Phiên 2", documents: [], messages: [] } };
      }
      if (path === "/api/v1/sessions") return { sessions: [session] };
      if (path.startsWith("/api/v1/sessions/")) return { session: path.endsWith("new") ? { id: "new", title: "Phiên 2", documents: [], messages: [] } : session };
      return { jobs: [] };
    });
    render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
    const create = await screen.findByRole("button", { name: "Tạo phiên làm việc mới" });
    await waitFor(() => expect(create.disabled).toBe(false));
    fireEvent.click(create);
    await screen.findByText("Đã tạo phiên làm việc mới.");
    await act(async () => {}); // let the notice effect start its timer
    await act(async () => { vi.advanceTimersByTime(7000); });
    expect(screen.queryByText("Đã tạo phiên làm việc mới.")).toBeNull();
    fireEvent.click(create);
    await screen.findByText("Không thể tạo phiên.");
    await act(async () => { vi.advanceTimersByTime(20000); });
    expect(screen.getByText("Không thể tạo phiên.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Đóng thông báo" }));
    expect(screen.queryByText("Không thể tạo phiên.")).toBeNull();
  } finally { vi.useRealTimers(); }
});

it("keeps a failed question with its retry when another question is sent", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [] };
  const keys = [];
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions") return { sessions: [session] };
    if (path === "/api/v1/sessions/chat") return { session };
    if (path.endsWith("/messages") && options?.method === "POST") {
      const { question } = JSON.parse(options.body);
      keys.push([question, options.headers["Idempotency-Key"]]);
      if (question === "First") throw Object.assign(new Error("Dịch vụ AI đang bận hoặc tạm thời không phản hồi. Hãy thử lại sau ít phút."), { code: "AI_PROVIDER_UNAVAILABLE" });
      return { user_message: { id: `u-${keys.length}`, role: "user", document_id: "doc", body: question }, assistant_message: { id: `a-${keys.length}`, role: "assistant", document_id: "doc", status: "completed", body: `Answer to ${question}` } };
    }
    return { jobs: [] };
  });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  const composer = view.container.querySelector("#chat-question");
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: "First" } });
  fireEvent.keyDown(composer, { key: "Enter" });
  await screen.findByText(/Dịch vụ AI đang bận/);
  expect(screen.getAllByText(/Dịch vụ AI đang bận/)).toHaveLength(1);
  expect(view.container.querySelector(".toast")).toBeNull();
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: "Second" } });
  fireEvent.keyDown(composer, { key: "Enter" });
  await screen.findByText("Answer to Second");
  expect(screen.getByText("First")).toBeTruthy();
  fireEvent.click(view.container.querySelector(".message.assistant.failed .retry-answer-button"));
  await waitFor(() => expect(keys).toHaveLength(3));
  expect(keys[2]).toEqual(keys[0]);
});

it("keeps a failed question in its place in the conversation and after a reload", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const saved = [
    { id: "q0", role: "user", document_id: "doc", body: "Zero" },
    { id: "a0", role: "assistant", document_id: "doc", reply_to_message_id: "q0", body: "Answer to Zero" },
  ];
  const session = () => ({ id: "chat", title: "My session", documents: [doc], messages: [...saved] });
  const keys = [];
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions") return { sessions: [session()] };
    if (path === "/api/v1/sessions/chat") return { session: session() };
    if (path.endsWith("/messages") && options?.method === "POST") {
      const { question } = JSON.parse(options.body);
      keys.push(options.headers["Idempotency-Key"]);
      if (question === "First") throw Object.assign(new Error("Máy chủ AI đang bận."), { code: "AI_PROVIDER_UNAVAILABLE" });
      const turn = [{ id: `u-${question}`, role: "user", document_id: "doc", body: question }, { id: `a-${question}`, role: "assistant", document_id: "doc", reply_to_message_id: `u-${question}`, status: "completed", body: `Answer to ${question}` }];
      saved.push(...turn);
      return { user_message: turn[0], assistant_message: turn[1] };
    }
    return { jobs: [] };
  });
  const bubbles = (container) => [...container.querySelectorAll(".chat-body article")].map((node) => node.querySelector("p, .answer-failure span")?.textContent);
  let view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  let composer = view.container.querySelector("#chat-question");
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: "First" } });
  fireEvent.keyDown(composer, { key: "Enter" });
  await screen.findByText("Máy chủ AI đang bận.");
  await waitFor(() => expect(composer.disabled).toBe(false));
  fireEvent.change(composer, { target: { value: "Second" } });
  fireEvent.keyDown(composer, { key: "Enter" });
  await screen.findByText("Answer to Second");
  await waitFor(() => expect(bubbles(view.container)).toEqual(["Zero", "Answer to Zero", "First", "Máy chủ AI đang bận.", "Second", "Answer to Second"]));

  cleanup();
  view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("Máy chủ AI đang bận.");
  await waitFor(() => expect(bubbles(view.container)).toEqual(["Zero", "Answer to Zero", "First", "Máy chủ AI đang bận.", "Second", "Answer to Second"]));
  fireEvent.click(view.container.querySelector(".message.assistant.failed .retry-answer-button"));
  await waitFor(() => expect(keys).toHaveLength(3));
  expect(keys[2]).toEqual(keys[0]);
});

it("sends the question that was still waiting before a reload again with the same key", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [] };
  sessionStorage.setItem("sourcelens-unsaved-questions-v1", JSON.stringify([{ id: "local-q", answer_id: "local-a", session_id: "chat", document_id: "doc", question: "Still running?", key: "key-1", sent_at: Date.now(), after: null }]));
  let release;
  const posted = [];
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions") return { sessions: [session] };
    if (path === "/api/v1/sessions/chat") return { session };
    if (path.endsWith("/messages") && options?.method === "POST") {
      posted.push(options.headers["Idempotency-Key"]);
      await new Promise((resolve) => { release = resolve; });
      return { user_message: { id: "u", role: "user", document_id: "doc", body: "Still running?" }, assistant_message: { id: "a", role: "assistant", document_id: "doc", status: "completed", body: "Saved answer" } };
    }
    return { jobs: [] };
  });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("Still running?");
  expect(view.container.querySelector(".typing-indicator")).toBeTruthy();
  await waitFor(() => expect(posted).toEqual(["key-1"]));
  await act(async () => release());
  await screen.findByText("Saved answer");
  expect(sessionStorage.getItem("sourcelens-unsaved-questions-v1")).toBeNull();
});

it("opens a conversation at its newest message", async () => {
  const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [
    { id: "q", role: "user", document_id: "doc", body: "Old question" },
    { id: "a", role: "assistant", document_id: "doc", reply_to_message_id: "q", body: "Newest answer" },
  ] };
  requestMock.mockImplementation(async (path) => path === "/api/v1/sessions" ? { sessions: [{ ...session, messages: [] }] } : path === "/api/v1/sessions/chat" ? { session } : { jobs: [] });
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("Newest answer");
  const body = view.container.querySelector(".chat-body");
  await waitFor(() => expect(Element.prototype.scrollTo).toHaveBeenCalledWith({ top: body.scrollHeight, behavior: "instant" }));
});

it.each([
  ["ready", "Đã đọc lại Report.pdf: 50 số liệu. Giữ lại 2 số đã sửa; 1 số không giữ được vì vị trí đã thay đổi. 1 câu trả lời dùng số đã thay đổi cần cập nhật."],
  ["failed", "Chưa đọc lại được Report.pdf. Hãy thử lại sau. 3 số bạn đã sửa vẫn được giữ cho lần đọc sau."],
])("tells what a re-extraction did once it ends (%s)", async (outcome, notice) => {
  let status = "ready";
  const rerun = () => requestMock.mock.calls.some(([path]) => path.endsWith("/extraction"));
  const history = () => status === "ready" && rerun()
    ? [{ edits_carried_over: ["k1", "k2"], edits_not_carried_over: [{ evidence_key: "k3", numeric_value: "5", code: "LOCATION_CHANGED" }], affected_message_ids: ["m1"] }]
    : [];
  const pending = () => status === "failed" ? [{ evidence_key: "k1" }, { evidence_key: "k2" }, { evidence_key: "k3" }] : [];
  const session = () => ({ id: "chat", title: "My session", messages: [], documents: [{ id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: status, numeric_evidence_count: 50, extraction_history: history(), pending_edits: pending() }] });
  requestMock.mockImplementation(async (path) => {
    if (path === "/health") return { capabilities: { reextraction: { status: "available" } } };
    if (path === "/api/v1/sessions") return { sessions: [session()] };
    if (path === "/api/v1/sessions/chat") { const value = session(); if (status === "processing") status = outcome; return { session: value }; }
    // The server flags answers only once the new reading is ready.
    if (path.endsWith("/extraction")) { status = "processing"; return { affected_message_ids: [] }; }
    return { jobs: [] };
  });
  render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  fireEvent.click(await screen.findByText("Trích xuất lại"));
  const dialog = await screen.findByRole("dialog", { name: "Đọc lại tài liệu này?" });
  expect(dialog.textContent).toContain("chỉ câu trả lời dùng số đã thay đổi mới được đánh dấu");
  fireEvent.click(await screen.findByRole("button", { name: "Đọc lại tài liệu" }));
  await screen.findByText(notice, {}, { timeout: 4000 });
});

it("names the account button and closes its menu with Escape", async () => {
  const session = { id: "chat", title: "My session", documents: [], messages: [] };
  requestMock.mockImplementation(async (path) => path === "/api/v1/sessions" ? { sessions: [session] } : path === "/api/v1/sessions/chat" ? { session } : { jobs: [] });
  render(<ThemeProvider><WorkspaceScreen user={{ display_name: "An", email: "an@example.test" }} onSignOut={() => {}} onNavigate={() => {}} /></ThemeProvider>);
  const account = await screen.findByRole("button", { name: "Tài khoản: An" });
  fireEvent.click(account);
  expect(await screen.findByRole("button", { name: /Đăng xuất/ })).toBeTruthy();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("button", { name: /Đăng xuất/ })).toBeNull();
  expect(screen.getByRole("link", { name: "Đến ô đặt câu hỏi" }).getAttribute("href")).toBe("#chat-question");
});

it("renames with Enter and gives focus back to the opener when a dialog closes", async () => {
  const session = { id: "chat", title: "My session", documents: [], messages: [] };
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions") return { sessions: [session] };
    if (path === "/api/v1/sessions/chat" && options?.method === "PATCH") { session.title = JSON.parse(options.body).title; return { session }; }
    if (path === "/api/v1/sessions/chat") return { session };
    return { jobs: [] };
  });
  render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  const trigger = await screen.findByRole("button", { name: "Tùy chọn My session" });
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("menuitem", { name: /Xóa/ }));
  await screen.findByRole("dialog", { name: "Xóa phiên này?" });
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);

  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("menuitem", { name: /Đổi tên/ }));
  const input = await screen.findByLabelText("Tên hiển thị");
  fireEvent.change(input, { target: { value: "Báo cáo quý" } });
  fireEvent.submit(input.form);
  await waitFor(() => expect(requestMock).toHaveBeenCalledWith("/api/v1/sessions/chat", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "Báo cáo quý" }) })));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.activeElement).toBe(trigger);
});

it("shows the server's own message when the PDF file cannot be loaded", async () => {
  pdfFailure.current = Object.assign(new Error("Unexpected server response (404)"), { name: "ResponseException", status: 404 });
  const doc = { id: "doc", file_name: "Gone.pdf", byte_size: 100, extraction_status: "ready", file_url: "/api/v1/sessions/chat/documents/doc/file" };
  const session = { id: "chat", title: "My session", documents: [doc], messages: [] };
  requestMock.mockImplementation(async (path) => {
    if (path === doc.file_url) throw Object.assign(new Error("Không tìm thấy tệp PDF đã lưu của tài liệu này."), { status: 404, code: "DOCUMENT_FILE_MISSING" });
    return path === "/api/v1/sessions" ? { sessions: [session] } : path === "/api/v1/sessions/chat" ? { session } : { jobs: [] };
  });
  render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  const error = await screen.findByText("Không tìm thấy tệp PDF đã lưu của tài liệu này.");
  expect(error.getAttribute("role")).toBe("alert");
  expect(requestMock).toHaveBeenCalledWith(doc.file_url, { headers: { Range: "bytes=0-0" } });
  expect(screen.queryByText(/Unexpected server response/)).toBeNull();
});
