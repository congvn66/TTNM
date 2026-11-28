/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ API: "http://localhost:8000", request: requestMock }));
import { useSwaps } from "./useSwaps.js";
import { headlineOf } from "./Notes.jsx";

const cell = (key, row, rowIndex, value) => ({ evidence_key: key, page_number: 1, bbox: [0.1, 0.1 * rowIndex, 0.2, 0.1 * rowIndex + 0.05], raw_text: String(value), current_numeric_value: String(value), data_status: "valid", table_locator: { table_region_key: "t", row_index: rowIndex, column_index: 1, row_header: row, column_header: "Quý 1" } });
const evidences = [cell("north", "Miền Bắc", 1, 18240), cell("total", "Tổng", 2, 42290), cell("q2", "Tổng Q2", 3, 49880)];
const input = (key, value) => ({ evidence_key: key, value, page: 1, bbox: [0.1, 0.1, 0.2, 0.15], label: key });

afterEach(() => requestMock.mockReset());

it("puts the page back on the answer's own cells when a swap is undone (F2-5)", async () => {
  const formula = { expression: "result = value('q2') - value('total')", result: "7590", inputs: [input("q2", "49880"), input("total", "42290")] };
  const answer = { answer: "Tăng 7.590.", evidence: [], formulas: [formula] };
  const base = headlineOf(answer);
  requestMock.mockResolvedValue({ status: "succeeded", formula: { expression: "result = value('q2') - value('north')", result: "31640", inputs: [input("q2", "49880"), input("north", "18240")] } });
  const focusOn = vi.fn();
  const { result } = renderHook(() => useSwaps({ basePath: "/d", evidences, dataKey: "k", focusOn, toast: vi.fn() }));
  const note = { id: "q", reply: { id: "a" } };
  act(() => result.current.start({ note, base, headline: base, formulaIndex: 0, index: 1 }));
  await act(async () => { await result.current.choose("north"); });
  expect(result.current.swaps.q.swap).toEqual({ total: "north" });
  act(() => result.current.undo("q"));
  expect(result.current.swaps.q).toBeUndefined();
  expect(focusOn).toHaveBeenLastCalledWith(base.chip);
});
