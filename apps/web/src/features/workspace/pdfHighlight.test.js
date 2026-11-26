import { expect, it } from "vitest";
import { quoteBoxes } from "./pdfHighlight.js";

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
