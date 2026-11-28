/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AnswerCard, PendingCard, ReadingCard } from "./Notes.jsx";

afterEach(cleanup);

const box = [0.1, 0.1, 0.2, 0.15];
const input = (key, value, label) => ({ evidence_key: key, value, page: 1, bbox: box, label });
const formula = { expression: "result = value('q2') - value('q1')", result: "7590", substitution: "Quý 2 trừ quý 1", inputs: [input("q2", "49880", "Tổng · Quý 2"), input("q1", "42290", "Tổng · Quý 1")] };
const reply = (extra = {}) => ({ id: "a", role: "assistant", status: "completed", structured_answer: { answer: "Tăng 7.590 triệu đồng, từ 42.290 lên 49.880.", formulas: [formula],
  evidence: [{ kind: "data", page: 1, bbox: box, evidence_key: "q1", value: "42290", label: "Tổng · Quý 1", data_status: "valid" }, { kind: "data", page: 1, bbox: box, evidence_key: "q2", value: "49880", label: "Tổng · Quý 2", data_status: "valid" },
    { kind: "text", page: 1, quote: "Tổng 42.290 49.880 — 14.525" }] }, ...extra });
const note = (extra) => ({ id: "q", question: { id: "q", body: "Thay đổi bao nhiêu?" }, reply: reply(extra) });
const props = { activeKey: null, onFocus: vi.fn(), onAsk: vi.fn(), onEdit: vi.fn() };

it("labels a difference, shows its formula, and leaves out a quote that is only a table row (F2-10)", () => {
  const { container } = render(<AnswerCard note={note()} {...props} />);
  expect(container.querySelector(".rd-headline-value span").textContent).toContain("Chênh lệch");
  // Each input is its tag, "số N: " for screen readers, and its value; the line ends with the result.
  expect(container.querySelector(".rd-formula .rd-result-line").textContent).toBe("1số 1: 49.880 − 2số 2: 42.290= 7.590");
  expect(container.querySelector(".rd-quote")).toBeNull();
});

it("after a swap, folds the AI's sentence away and lists the chosen cell (F2-6)", () => {
  const swap = { formulaIndex: 0, swap: { q1: "north" }, warning: "", formula: { ...formula, expression: "result = value('q2') - value('north')", result: "31640", inputs: [input("q2", "49880", "Tổng · Quý 2"), input("north", "18240", "Miền Bắc · Quý 1")] } };
  const { container } = render(<AnswerCard note={note()} {...props} swap={swap} onUndoSwap={vi.fn()} />);
  expect(container.querySelector(".rd-headline-value b").textContent).toBe("31.640");
  expect(container.querySelector("details.rd-orig summary").textContent).toBe("Câu trả lời với ô gốc");
  const sources = [...container.querySelectorAll(".rd-source-list b")].map((node) => node.textContent);
  expect(sources).toEqual(["18.240", "49.880"]);
});

it("drops 'Số liệu đã thay đổi' once the numbers are back to what the answer used (F2-9)", () => {
  const now = (q1) => [{ evidence_key: "q1", current_numeric_value: q1, original_numeric_value: "42290" }, { evidence_key: "q2", current_numeric_value: "49880", original_numeric_value: "49880" }];
  const { rerender } = render(<AnswerCard note={note({ needs_update: true })} {...props} evidences={now("42380")} />);
  expect(screen.getByText(/Số liệu đã thay đổi/)).toBeTruthy();
  rerender(<AnswerCard note={note({ needs_update: true })} {...props} evidences={now("42290")} />);
  expect(screen.queryByText(/Số liệu đã thay đổi/)).toBeNull();
});

it("says an answer uses a corrected number the PDF prints differently (F2-11)", () => {
  const answer = { id: "a", status: "completed", structured_answer: { answer: "Mục tiêu là 250 tỷ đồng.", evidence: [{ kind: "data", page: 2, evidence_key: "goal", value: "250", label: "Mục tiêu", data_status: "valid" }, { kind: "text", page: 2, quote: "Mục tiêu lợi nhuận năm nay là 220 tỷ đồng" }] } };
  const { container } = render(<AnswerCard note={{ id: "q", question: { body: "Mục tiêu?" }, reply: answer }} {...props} evidences={[{ evidence_key: "goal", current_numeric_value: "250", original_numeric_value: "220" }]} />);
  expect(screen.getByText("Dùng số đã sửa: 250, PDF ghi 220")).toBeTruthy();
  expect(container.querySelector(".rd-quote small").textContent).toContain("220 đã sửa thành 250");
});

it("shows a stopped answer without an error colour, and a busy one with when to retry (F2-4)", () => {
  const { container, rerender } = render(<AnswerCard note={{ id: "q", question: { body: "x" }, reply: { id: "a", status: "failed", body: "Đã dừng tạo câu trả lời." } }} {...props} />);
  expect(container.querySelector(".rd-qa.stopped")).toBeTruthy();
  expect(screen.getByText("Đã dừng")).toBeTruthy();
  rerender(<AnswerCard note={{ id: "q", question: { body: "x" }, reply: { id: "a", status: "failed", body: "Không thể tạo câu trả lời. Hãy thử lại.", error_code: "RATE_LIMITED" } }} {...props} />);
  expect(screen.getByText("Hệ thống đang bận. Thử lại sau một phút.")).toBeTruthy();
});

it("offers Dừng on a question still being sent (F2-3)", () => {
  const stop = vi.fn();
  render(<PendingCard item={{ id: "p", question: "Hỏi", status: "asking", startedAt: Date.now(), stop }} onRetry={vi.fn()} onDismiss={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Dừng" }));
  expect(stop).toHaveBeenCalled();
});

it("says a reading that stopped can be tried again (EXTRACTION_STOPPED)", async () => {
  const { FailedCard } = await import("./Notes.jsx");
  const retry = vi.fn();
  render(<FailedCard report={{ id: "r", extraction_status: "failed", extraction_error: "EXTRACTION_STOPPED", can_retry: true }} onRetry={retry} />);
  expect(screen.getByRole("heading", { name: "Chưa đọc xong báo cáo này" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
  expect(retry).toHaveBeenCalled();
});

it("shows no moving bar while a report waits for a worker (C2-9)", () => {
  const { rerender } = render(<ReadingCard report={{ id: "r", extraction_status: "queued", created_at: new Date(Date.now() - 60_000).toISOString(), page_count: 3 }} />);
  expect(screen.getByRole("heading", { name: "Đang chờ đọc…" })).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
  rerender(<ReadingCard report={{ id: "r", extraction_status: "processing", created_at: new Date(Date.now() - 60_000).toISOString(), page_count: 3 }} />);
  expect(screen.getByRole("heading", { name: "Đang đọc báo cáo…" })).toBeTruthy();
  // The bar counts from when reading started, not from the upload.
  expect(Number(screen.getByRole("progressbar").getAttribute("aria-valuenow"))).toBeLessThan(10);
});
