/** @vitest-environment jsdom */
import { expect, it } from "vitest";
import { previewText, totalImpact, withSavedRevision } from "./DataPanel.jsx";

const cell = (key, row, rowIndex, value) => ({ evidence_key: key, page_number: 1, current_numeric_value: String(value), data_status: "valid", table_locator: { table_region_key: "t", row_index: rowIndex, column_index: 1, row_header: row, column_header: "Quý 1" } });

it("says what an edit does to its column's total against how the column stands now (F2-7)", () => {
  const off = [cell("a", "Bắc", 1, 10), cell("b", "Nam", 2, 20), cell("t", "Tổng", 3, 33)];
  expect(totalImpact(off, off[2], "30")).toBe("Tổng cột sẽ khớp");
  expect(totalImpact(off, off[2], "34")).toBe("Tổng cột vẫn lệch 4");
  const ok = [cell("a", "Bắc", 1, 10), cell("b", "Nam", 2, 20), cell("t", "Tổng", 3, 30)];
  expect(totalImpact(ok, ok[0], "15")).toBe("Tổng cột sẽ lệch 5");
  expect(totalImpact(ok, ok[2], "30.0")).toBe("Tổng cột vẫn khớp");
});

it("adds the plain digits only when the reading may surprise (F2-7)", () => {
  expect(previewText({ plain_value: "42380" }, "42.380")).toBe("42.380");
  expect(previewText({ plain_value: "42380" }, "42380")).toBe("42.380");
  expect(previewText({ plain_value: "42380" }, "42,380")).toBe("42.380 (= 42380)");
});

it("applies a saved edit at once, so the cell card does not wait for the next fetch (F2-8)", () => {
  const data = { data_revision: 3, evidences: [{ evidence_key: "a", current_numeric_value: "42290", current_revision_id: "r1", revision_count: 1, data_status: "ambiguous" }, { evidence_key: "b", current_numeric_value: "1" }] };
  const next = withSavedRevision(data, "a", { data_revision: 4, revision: { id: "r2", numeric_value: "42380" } });
  expect(next.evidences[0]).toMatchObject({ current_numeric_value: "42380", current_revision_id: "r2", revision_count: 2, data_status: "valid" });
  expect(next.evidences[1]).toBe(data.evidences[1]);
  expect(next.data_revision).toBe(4);
  expect(withSavedRevision(data, "a", {})).toBe(data);
});
