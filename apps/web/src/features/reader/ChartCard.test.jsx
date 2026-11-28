import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChartCard } from "./ChartCard.jsx";

const cell = (r, c, header, value, name, extra = {}) => ({ evidence_key: `k-${r}-${c}`, page_number: 1, bbox: [0.3 + c * 0.1, 0.3 + r * 0.02, 0.35 + c * 0.1, 0.31 + r * 0.02], current_numeric_value: value == null ? null : String(value), original_numeric_value: value == null ? null : String(value), data_status: "valid", raw_text: value == null ? "—" : String(value),
  table_locator: { table_region_key: "t", row_index: r, column_index: c, row_header: name, column_header: header }, ...extra });
const noop = () => {};
const draw = (evidences, chart = {}) => renderToStaticMarkup(<ChartCard chart={{ id: "c1", keys: evidences.map((item) => item.evidence_key), ...chart }} evidences={evidences} activeKey={null} onPeek={noop} onOpenCell={noop} onShowCells={noop} onChange={noop} onRemove={noop} />);

describe("ChartCard never draws broken numbers", () => {
  const cases = {
    "a visible column with no numbers": [[cell(1, 0, "A · 2025", 5, "x"), cell(2, 0, "A · 2025", 6, "y"), cell(1, 1, "A · 2026", null, "x"), cell(2, 1, "A · 2026", null, "y")], { off: ["0"] }],
    "all negative": [[cell(1, 0, "Lỗ", -5, "x"), cell(2, 0, "Lỗ", -9, "y")]],
    "all zero": [[cell(1, 0, "A", 0, "x"), cell(2, 0, "A", 0, "y")]],
    "huge numbers": [[cell(1, 0, "A", 123456789012, "x"), cell(2, 0, "A", 98765432109, "y")]],
    "tiny decimals": [[cell(1, 0, "A", 0.0012, "x"), cell(2, 0, "A", 0.0031, "y")]],
    "a long row name": [[cell(1, 0, "A", 10, "Doanh thu bán hàng và cung cấp dịch vụ cho khách hàng trong nước"), cell(2, 0, "A", 20, "y")]],
    "one row with a null period": [[cell(1, 0, "A · 2024", 10, "x"), cell(1, 1, "A · 2025", null, "x"), cell(1, 2, "A · 2026", 30, "x")]],
    "share mode stored but no totals": [[cell(1, 0, "A", 10, "x"), cell(2, 0, "A", 20, "y")], { mode: "share" }],
  };
  for (const [name, [evidences, chart]] of Object.entries(cases)) {
    it(name, () => {
      const html = draw(evidences, chart);
      expect(html).not.toMatch(/NaN|Infinity|undefined/);
    });
  }
});
