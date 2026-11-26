/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ API: "http://localhost:8000", request: requestMock }));
vi.mock("pdfjs-dist", () => ({ GlobalWorkerOptions: {}, getDocument: () => ({ promise: Promise.reject(new Error("preview unavailable in test")), destroy: vi.fn() }) }));
import WorkspaceScreen from "./WorkspaceScreen.jsx";
import { ThemeProvider } from "../theme/ThemeProvider.jsx";

const base = "/api/v1/sessions/chat/documents/doc";
const doc = { id: "doc", file_name: "Report.pdf", byte_size: 100, extraction_status: "ready" };
const row = (key, extra) => ({
  evidence_key: key, page_number: 1, bbox: [0.1, 0.1, 0.2, 0.2], raw_text: "21.350", method_label: "đọc từ ô bảng", data_status: "valid",
  table_locator: { row_header: "Miền Bắc", column_header: "Doanh thu thuần / Quý 2/2026" }, semantic: { measure: "doanh_thu" },
  original_numeric_value: "21350", current_numeric_value: "21350", current_revision_id: `${key}-r1`, revision_count: 1, ...extra,
});

function mockApi(handlers, messages = []) {
  const session = { id: "chat", title: "My session", documents: [doc], messages };
  requestMock.mockImplementation(async (path, options) => {
    for (const [match, handler] of handlers) if (path.startsWith(match)) return handler(path, options);
    if (path === "/api/v1/sessions") return { sessions: [{ ...session, messages: [] }] };
    if (path === "/api/v1/sessions/chat") return { session };
    return { jobs: [] };
  });
}

async function openDrawer() {
  const view = render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  const button = await screen.findByRole("button", { name: "Bằng chứng" });
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  return { view, drawer: await screen.findByRole("dialog", { name: "Số liệu trong tài liệu" }) };
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); Element.prototype.scrollTo = vi.fn(); });
afterEach(() => { cleanup(); requestMock.mockReset(); });

it("checks the typed number first, asks to confirm it, then saves the same text", async () => {
  const posts = [];
  let saved = false;
  mockApi([
    [`${base}/evidences/k1/revisions`, async (path, options) => {
      posts.push({ path, body: JSON.parse(options.body) });
      if (path.endsWith("?dry_run=true")) return { parsed_value: "21500", display: "21.500", locale: "vi" };
      saved = true;
      return { revision: { old_numeric_value: "21350", numeric_value: "21500" }, display: "21.500", affected_message_ids: [] };
    }],
    [`${base}/evidences`, async () => ({ evidences: [row("k1", saved ? { current_numeric_value: "21500", revision_count: 2 } : {})] })],
  ]);
  const { drawer } = await openDrawer();
  expect(within(drawer).getByText("Miền Bắc · Doanh thu thuần / Quý 2/2026")).toBeTruthy();
  expect(within(drawer).queryByText(/revision/i)).toBeNull();
  fireEvent.click(within(drawer).getByRole("button", { name: "Sửa số: Miền Bắc · Doanh thu thuần / Quý 2/2026" }));
  fireEvent.change(within(drawer).getByLabelText("Giá trị mới"), { target: { value: "21.500" } });
  fireEvent.change(within(drawer).getByLabelText("Lý do sửa"), { target: { value: "Đối chiếu PDF" } });
  fireEvent.click(within(drawer).getByRole("button", { name: "Kiểm tra số" }));
  await within(drawer).findByText("21.500", { selector: ".evidence-edit-preview b" });
  expect(posts).toHaveLength(1);
  fireEvent.click(within(drawer).getByRole("button", { name: "Xác nhận lưu" }));
  await screen.findByText("Đã lưu 21.350 → 21.500.");
  expect(posts.map((item) => item.path)).toEqual([`${base}/evidences/k1/revisions?dry_run=true`, `${base}/evidences/k1/revisions`]);
  for (const { body } of posts) expect(body).toEqual({ input_text: "21.500", reason: "Đối chiếu PDF", expected_revision_id: "k1-r1" });
  await within(drawer).findByText("Đã sửa · số gốc trong PDF: 21.350");
});

it("keeps the form and the typed text open with one inline error when the number is unclear", async () => {
  mockApi([
    [`${base}/evidences/k1/revisions`, async () => {
      throw Object.assign(new Error("Không rõ 21,500 là hai mươi mốt nghìn năm trăm hay hai mươi mốt phẩy năm."), { status: 422, code: "NUMBER_FORMAT_AMBIGUOUS" });
    }],
    [`${base}/evidences`, async () => ({ evidences: [row("k1")] })],
  ]);
  const { drawer } = await openDrawer();
  fireEvent.click(within(drawer).getByRole("button", { name: /^Sửa số/ }));
  fireEvent.change(within(drawer).getByLabelText("Giá trị mới"), { target: { value: "21,500" } });
  fireEvent.change(within(drawer).getByLabelText("Lý do sửa"), { target: { value: "Đối chiếu PDF" } });
  fireEvent.click(within(drawer).getByRole("button", { name: "Kiểm tra số" }));
  const alert = await within(drawer).findByRole("alert");
  expect(alert.textContent).toMatch(/Không rõ 21,500/);
  expect(screen.getAllByText(/Không rõ 21,500/)).toHaveLength(1);
  expect(within(drawer).getByLabelText("Giá trị mới").value).toBe("21,500");
  expect(within(drawer).queryByText(/Sẽ lưu/)).toBeNull();
});

it("lists the edit history of a number with old and new value and the reason", async () => {
  mockApi([
    [`${base}/evidences/k1/revisions`, async () => ({ revisions: [
      { id: "r1", action: "initialize", numeric_value: "21350", created_at: "2026-11-20T08:00:00Z" },
      { id: "r2", action: "edit", old_numeric_value: "21350", numeric_value: "21500", reason: "Đối chiếu PDF", created_at: "2026-11-21T09:30:00Z" },
    ] })],
    [`${base}/evidences`, async () => ({ evidences: [row("k1", { current_numeric_value: "21500", revision_count: 2 }), row("k2", { table_locator: { row_header: "Tổng / -", column_header: "Lợi nhuận gộp" } })] })],
  ]);
  const { drawer } = await openDrawer();
  expect(within(drawer).getByText("Tổng · Lợi nhuận gộp")).toBeTruthy();
  expect(within(drawer).getAllByRole("button", { name: "Lịch sử sửa" })).toHaveLength(1);
  fireEvent.click(within(drawer).getByRole("button", { name: "Lịch sử sửa" }));
  const item = await within(drawer).findByText("21.350 → 21.500");
  expect(item.parentElement.textContent).toContain("Đối chiếu PDF");
  expect(within(drawer).getByText("Đọc từ PDF:", { exact: false })).toBeTruthy();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "Số liệu trong tài liệu" })).toBeNull();
});

it("marks a number in an answer as edited only after a real edit", async () => {
  const card = (key, value) => ({ kind: "data", page: 1, evidence_key: key, label: `ev-${key}`, value, raw_text: "21.350", method_label: "đọc từ ô bảng", data_status: "valid" });
  mockApi([[`${base}/evidences`, async () => ({ evidences: [row("k1"), row("k2", { current_numeric_value: "21500", revision_count: 2 })] })]], [
    { id: "q", role: "user", document_id: "doc", body: "Doanh thu?" },
    { id: "a", role: "assistant", document_id: "doc", reply_to_message_id: "q", body: "x", structured_answer: { presentation: "document_assistant", answer: "Doanh thu", sections: [], tables: [], claims: [], warnings: [], formulas: [], evidence: [card("k1", "21350"), card("k2", "21500")] } },
  ]);
  render(<ThemeProvider><WorkspaceScreen /></ThemeProvider>);
  await screen.findByText("21.350");
  await screen.findByText(/Đã sửa trong Dữ liệu/);
  expect(screen.getAllByText(/Đã sửa trong Dữ liệu/)).toHaveLength(1);
  expect(screen.getByText("21.500").closest(".evidence-item").textContent).toContain("Đã sửa trong Dữ liệu");
  expect(screen.queryByText(/ev-k1/)).toBeNull();
  expect(screen.getAllByText("Số ở trang 1")).toHaveLength(2);
});

it("offers the readings of an ambiguous number and sends the chosen one as numeric_value", async () => {
  const bodies = [];
  mockApi([
    [`${base}/evidences/k1/revisions`, async (path, options) => {
      const body = JSON.parse(options.body);
      bodies.push(body);
      if (body.input_text) throw Object.assign(new Error("Chưa rõ 1.250 là một nghìn hai trăm năm mươi hay một phẩy hai lăm."), { status: 422, code: "NUMBER_FORMAT_AMBIGUOUS", detail: { readings: ["1250", "1.250"] } });
      return { parsed_value: body.numeric_value, display: body.numeric_value === "1250" ? "1.250" : "1,25", locale: "vi" };
    }],
    [`${base}/evidences`, async () => ({ evidences: [row("k1")] })],
  ]);
  const { drawer } = await openDrawer();
  fireEvent.click(within(drawer).getByRole("button", { name: /^Sửa số/ }));
  fireEvent.change(within(drawer).getByLabelText("Giá trị mới"), { target: { value: "1.250" } });
  fireEvent.change(within(drawer).getByLabelText("Lý do sửa"), { target: { value: "Đối chiếu PDF" } });
  fireEvent.click(within(drawer).getByRole("button", { name: "Kiểm tra số" }));
  const choices = await within(drawer).findByRole("group", { name: "Chọn số bạn muốn lưu" });
  fireEvent.click(within(choices).getByRole("button", { name: "1.250" }));
  await within(drawer).findByText("1.250", { selector: ".evidence-edit-preview b" });
  expect(bodies[1]).toEqual({ numeric_value: "1250", reason: "Đối chiếu PDF", expected_revision_id: "k1-r1" });
  expect(bodies[0].input_text).toBe("1.250");
});
