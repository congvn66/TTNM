import { expect, it } from "vitest";
import { cellBands, quoteBoxes } from "./pdfHighlight.js";

// Identity page transform, 1000 x 1000 page, scale 1.
const viewport = { width: 1000, height: 1000, scale: 1, transform: [1, 0, 0, 1, 0, 0] };
const run = (str, x, y, width) => ({ str, width, transform: [10, 0, 0, 10, x, y] });

it("marks only the quoted words inside a paragraph line", () => {
  const boxes = quoteBoxes([run("Doanh thu tăng 31% so với", 100, 500, 250), run("cùng kỳ năm trước.", 100, 520, 180)], viewport, "tăng 31%");
  expect(boxes).toHaveLength(1);
  const [left, , right] = boxes[0];
  expect(left).toBeGreaterThan(0.1);
  expect(right).toBeLessThan(0.35);
  expect(right - left).toBeLessThan(0.15);
});

it("gives one box per line when the quote crosses lines", () => {
  const boxes = quoteBoxes([run("Doanh thu tăng 31% so với", 100, 500, 250), run("cùng kỳ năm trước.", 100, 520, 180), run("Ghi chú khác", 100, 540, 120)], viewport, "so với cùng kỳ");
  expect(boxes).toHaveLength(2);
  expect(boxes[0][1]).toBeLessThan(boxes[1][1]);
});

it("finds nothing for a quote that is not on the page", () => {
  expect(quoteBoxes([run("Doanh thu", 100, 500, 90)], viewport, "lợi nhuận")).toEqual([]);
});

it("tints the row out to its name and the column up to its header", () => {
  const cell = (row, column) => ({ evidence_key: `ev-${row}-${column}`, page_number: 1, bbox: [0.5 + column * 0.1, 0.5 + row * 0.02, 0.56 + column * 0.1, 0.515 + row * 0.02], table_locator: { table_region_key: "t1", row_index: row, column_index: column } });
  const evidences = [0, 1, 2].flatMap((row) => [0, 1].map((column) => cell(row, column)));
  const rowName = [0.1, 0.52, 0.3, 0.535]; // text left of the table on row 1
  const header = [0.5, 0.47, 0.55, 0.485]; // "2024" above column 0
  const bands = cellBands(evidences, "ev-1-0", 1, [rowName, header]);
  expect(bands.row[0]).toBe(0.1);
  expect(bands.row[2]).toBeCloseTo(0.66);
  expect(bands.column[1]).toBe(0.47);
  expect(bands.column[3]).toBeCloseTo(0.555);
  expect(cellBands(evidences, "ev-1-0", 2, [])).toBeNull();
  expect(cellBands(evidences.slice(0, 3), "ev-1-0", 1, [])).toBeNull();
});
