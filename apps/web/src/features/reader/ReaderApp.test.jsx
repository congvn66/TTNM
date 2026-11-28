/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ API: "http://localhost:8000", request: requestMock }));
vi.mock("pdfjs-dist", () => ({ GlobalWorkerOptions: {}, getDocument: () => ({ promise: Promise.reject(new Error("no pdf in test")), destroy: vi.fn() }) }));
import ReaderApp, { rereadSummary } from "./ReaderApp.jsx";
import { pairNotes } from "./useConversation.js";
import { friendlyError } from "./Notes.jsx";
import { ThemeProvider } from "../theme/ThemeProvider.jsx";

const ready = { id: "doc", file_name: "Bao-cao.pdf", page_count: 3, extraction_status: "ready", created_at: "2026-11-26T10:00:00Z" };
const cell = (key, row, rowIndex, value) => ({ evidence_key: key, page_number: 1, bbox: [0.1, 0.1, 0.2, 0.2], raw_text: String(value), method_label: "đọc từ ô bảng", current_numeric_value: String(value), data_status: "valid", table_locator: { table_region_key: "t", row_index: rowIndex, column_index: 1, row_header: row, column_header: "Doanh thu · Quý 2/2026" } });
const evidences = [cell("a", "Bắc", 1, 10), cell("b", "Nam", 2, 20), cell("t", "Tổng", 3, 30)];

function api({ documents = [ready], messages = [], onAsk } = {}) {
  const state = { documents, messages };
  requestMock.mockImplementation(async (path, options) => {
    if (path === "/api/v1/sessions" && !options) return { sessions: [{ id: "s", title: "Báo cáo của tôi", documents: state.documents, messages: [] }] };
    if (path === "/api/v1/sessions/s") return { session: { id: "s", documents: state.documents, messages: state.messages } };
    if (path.endsWith("/evidences")) return { data_revision: 0, evidences };
    if (path.endsWith("/brief")) return { status: "ready", brief: { structured_answer: { answer: "Báo cáo doanh thu quý 2/2026 của công ty mẫu.\n- Tổng doanh thu đạt 30.\nCần chú ý: số liệu chưa kiểm toán.", evidence: [{ kind: "data", page: 1, value: "30", raw_text: "30", label: "Tổng · Quý 2", evidence_key: "t", data_status: "valid", bbox: [0.1, 0.1, 0.2, 0.2] }] } } };
    if (path.endsWith("/messages") && options?.method === "POST") return onAsk(state, JSON.parse(options.body));
    return {};
  });
  return state;
}

beforeEach(() => { localStorage.clear(); Element.prototype.scrollTo = vi.fn(); });
afterEach(() => { cleanup(); requestMock.mockReset(); vi.useRealTimers(); });

const renderApp = () => render(<ThemeProvider><ReaderApp /></ThemeProvider>);

it("opens on the home screen with the drop zone, the sample and the reports in the sidebar", async () => {
  api();
  renderApp();
  expect(await screen.findByText("Kéo tệp PDF vào đây")).toBeTruthy();
  expect(screen.getByText("Mở báo cáo mẫu")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Bao-cao" }));
  expect(await screen.findByText(/Báo cáo doanh thu quý 2\/2026/)).toBeTruthy();
  expect(screen.getByText("Cần chú ý")).toBeTruthy();
  expect(screen.queryByText(/Đọc được/)).toBeNull();
});

it("keeps the question box usable while the AI answers, then shows the answer with a tappable number", async () => {
  let release;
  api({ onAsk: (state, body) => new Promise((resolve) => { release = () => {
    state.messages = [
      { id: "q", role: "user", document_id: "doc", body: body.question },
      { id: "a", role: "assistant", document_id: "doc", reply_to_message_id: "q", status: "completed", body: "Tổng là 30.", structured_answer: { answer: "Tổng là 30.", evidence: [{ kind: "data", page: 1, value: "30", raw_text: "30", label: "Tổng · Quý 2", evidence_key: "t", data_status: "valid", bbox: [0.1, 0.1, 0.2, 0.2] }] } },
    ];
    resolve({ assistant_message: state.messages[1] });
  }; }) });
  localStorage.setItem("sourcelens-report-v2", "doc");
  renderApp();
  const box = await screen.findByLabelText("Câu hỏi về báo cáo");
  fireEvent.change(box, { target: { value: "Tổng là bao nhiêu?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByText(/Đang trả lời…/)).toBeTruthy();
  expect(box.disabled).toBe(false);
  await act(async () => { release(); });
  const answer = await waitFor(() => { const node = document.querySelector(".rd-qa .rd-answer"); if (!node) throw new Error("no answer yet"); return node; });
  expect(answer.textContent).toBe("Tổng là 30.");
  const chip = answer.querySelector(".rd-chip");
  expect(chip.textContent).toBe("30");
  fireEvent.click(chip);
  expect(chip.getAttribute("aria-pressed")).toBe("true");
});

it("shows a failed question with a way to retry", async () => {
  api({ onAsk: async () => { throw new Error("Dịch vụ AI đang bận."); } });
  localStorage.setItem("sourcelens-report-v2", "doc");
  renderApp();
  const box = await screen.findByLabelText("Câu hỏi về báo cáo");
  fireEvent.change(box, { target: { value: "Hỏi gì đó" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await screen.findByText(friendlyError(new Error("Dịch vụ AI đang bận.")))).toBeTruthy();
  expect(screen.getByRole("button", { name: "Thử lại" })).toBeTruthy();
});

it("shows reading progress, then announces when the report is ready", async () => {
  const state = api({ documents: [{ ...ready, extraction_status: "processing", created_at: new Date().toISOString() }] });
  localStorage.setItem("sourcelens-report-v2", "doc");
  renderApp();
  expect(await screen.findByRole("heading", { name: /Đang đọc báo cáo/ })).toBeTruthy();
  expect(screen.getByRole("progressbar")).toBeTruthy();
  state.documents = [ready];
  await waitFor(() => expect(screen.getByText("Bao-cao.pdf đã sẵn sàng")).toBeTruthy(), { timeout: 4000 });
});

it("pairs answers with their questions even when replies come first", () => {
  const notes = pairNotes([
    { id: "a2", role: "assistant", reply_to_message_id: "q2" },
    { id: "q1", role: "user" },
    { id: "a1", role: "assistant", reply_to_message_id: "q1" },
    { id: "q2", role: "user" },
  ]);
  expect(notes.map((note) => [note.question?.id, note.reply?.id])).toEqual([["q1", "a1"], ["q2", "a2"]]);
});

it("pairs replies without a question link by time order", () => {
  const notes = pairNotes([
    { id: "q1", role: "user" }, { id: "a1", role: "assistant" },
    { id: "q2", role: "user" }, { id: "a2", role: "assistant" },
  ]);
  expect(notes.map((note) => [note.question?.id, note.reply?.id])).toEqual([["q1", "a1"], ["q2", "a2"]]);
});

it("says how many answers need asking again after a re-read, only when there are some", () => {
  expect(rereadSummary({ file_name: "A.pdf", extraction_history: [{}, { affected_message_ids: ["m1", "m2"] }] })).toBe("Đã đọc lại A.pdf · 2 câu trả lời cần hỏi lại");
  expect(rereadSummary({ file_name: "A.pdf", extraction_history: [{}, { affected_message_ids: [] }] })).toBe("Đã đọc lại A.pdf");
});

it("shows a waiting card with a stop button for an answer the worker is still writing", async () => {
  api({ messages: [
    { id: "q", role: "user", document_id: "doc", body: "Hỏi chậm" },
    { id: "a", role: "assistant", document_id: "doc", status: "processing", body: "", created_at: new Date().toISOString() },
  ] });
  localStorage.setItem("sourcelens-report-v2", "doc");
  renderApp();
  expect(await screen.findByText(/Đang trả lời…/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Dừng" })).toBeTruthy();
});
