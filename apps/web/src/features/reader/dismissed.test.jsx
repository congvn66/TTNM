/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { isOpenProblem, loadDismissed, saveDismissed } from "./dismissed.js";
import { BriefCard } from "./Notes.jsx";
import { buildBriefing } from "./reportChecks.js";

afterEach(() => { cleanup(); localStorage.clear(); });

const cell = (key, row, rowIndex, value) => ({ evidence_key: key, page_number: 1, bbox: [0.1, 0.1, 0.2, 0.2], raw_text: String(value), current_numeric_value: String(value), data_status: "valid", table_locator: { table_region_key: "t", row_index: rowIndex, column_index: 1, row_header: row, column_header: "Doanh thu · Quý 2/2026" } });
// 10 + 20 is not 35, so the total check fails.
const briefing = buildBriefing([cell("a", "Bắc", 1, 10), cell("b", "Nam", 2, 20), cell("t", "Tổng", 3, 35)]);
const problem = briefing.checks[0];

it("keeps dismissals per report and forgets a report with none left", () => {
  saveDismissed("r1", new Set([problem.chip.key]));
  saveDismissed("r2", new Set(["other"]));
  expect([...loadDismissed("r1")]).toEqual([problem.chip.key]);
  expect(isOpenProblem(problem, loadDismissed("r1"))).toBe(false);
  expect(isOpenProblem(problem, loadDismissed("r2"))).toBe(true);
  saveDismissed("r1", new Set());
  expect(JSON.parse(localStorage.getItem("sourcelens-dismissed-v1"))).toEqual({ r2: ["other"] });
});

it("hides a dismissed problem in the summary and offers to show it again, without claiming the totals match", () => {
  const onDismiss = vi.fn();
  const onRestore = vi.fn();
  const props = { brief: { status: "ready", answer: { answer: "Báo cáo quý 2.", evidence: [], formulas: [] } }, briefing, onDismiss, onRestore, onFocus: () => {}, onAsk: () => {}, onOpenData: () => {} };
  const { rerender } = render(<BriefCard {...props} />);
  fireEvent.click(screen.getByRole("button", { name: /Bỏ qua/ }));
  expect(onDismiss).toHaveBeenCalledWith(problem);

  rerender(<BriefCard {...props} dismissed={new Set([problem.chip.key])} />);
  expect(screen.queryByText("Tổng không khớp")).toBeNull();
  expect(screen.queryByText(/dòng tổng khớp/)).toBeNull();
  expect(screen.getByText(/Đã ẩn 1/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Hiện lại" }));
  expect(onRestore).toHaveBeenCalled();
});
