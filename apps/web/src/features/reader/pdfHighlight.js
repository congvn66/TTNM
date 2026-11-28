// PDF.js represents affine transforms as [a, b, c, d, e, f]. Keeping this
// tiny operation local avoids pulling the whole PDF.js runtime into the
// initial bundle just to derive a citation box from the already-rendered text.
function multiplyTransform(first, second) {
  return [
    first[0] * second[0] + first[2] * second[1],
    first[1] * second[0] + first[3] * second[1],
    first[0] * second[2] + first[2] * second[3],
    first[1] * second[2] + first[3] * second[3],
    first[0] * second[4] + first[2] * second[5] + first[4],
    first[1] * second[4] + first[3] * second[5] + first[5],
  ];
}

const compact = (value) => String(value ?? "").normalize("NFKC").replace(/\s+/g, "").toLocaleLowerCase("vi");
const clamp = (value) => Math.max(0, Math.min(1, value));

/**
 * Normalised boxes [x0, y0, x1, y1] of the first place the quote appears in
 * the page text: one box per text run, trimmed to the quoted characters, so a
 * quote inside a paragraph marks only its own words. Whitespace is ignored
 * when matching because PDF text runs split and join words unpredictably.
 */
export function quoteBoxes(textItems, viewport, quote) {
  const quoteText = compact(quote);
  if (!quoteText || !viewport) return [];
  const runs = textItems.map((item) => compact(item.str));
  const start = runs.join("").indexOf(quoteText);
  if (start < 0) return [];
  const end = start + quoteText.length;
  const boxes = [];
  let cursor = 0;
  textItems.forEach((item, index) => {
    const runStart = cursor;
    const runEnd = cursor + runs[index].length;
    cursor = runEnd;
    if (runEnd <= start || runStart >= end || runEnd === runStart) return;
    const transformed = multiplyTransform(viewport.transform, item.transform || [1, 0, 0, 1, 0, 0]);
    const fontSize = Math.max(6, Math.hypot(transformed[2], transformed[3]));
    const width = Math.max(2, Number(item.width || 0) * viewport.scale);
    const length = runEnd - runStart;
    const left = clamp((transformed[4] + width * (Math.max(start, runStart) - runStart) / length) / viewport.width);
    const right = clamp((transformed[4] + width * (Math.min(end, runEnd) - runStart) / length) / viewport.width);
    const top = clamp((transformed[5] - fontSize) / viewport.height);
    const bottom = clamp((transformed[5] + Math.max(2, fontSize * 0.18)) / viewport.height);
    boxes.push([left, top, Math.max(left, right), Math.max(top, bottom)]);
  });
  return boxes;
}

/** A box as [x0, y0, x1, y1] in 0..1, or null when it is not a real box. */
export function clampBox(value) {
  const raw = Array.isArray(value) ? value : [value?.x0, value?.y0, value?.x1, value?.y1];
  if (raw.length !== 4 || raw.some((item) => !Number.isFinite(Number(item)))) return null;
  const [x0, y0, x1, y1] = raw.map((item) => clamp(Number(item)));
  return x1 > x0 && y1 > y0 ? [x0, y0, x1, y1] : null;
}

/** Normalised box of every text run on the page. */
export function textRunBoxes(textItems, viewport) {
  if (!viewport) return [];
  return textItems.map((item) => {
    const transformed = multiplyTransform(viewport.transform, item.transform || [1, 0, 0, 1, 0, 0]);
    const fontSize = Math.max(6, Math.hypot(transformed[2], transformed[3]));
    const width = Math.max(2, Number(item.width || 0) * viewport.scale);
    return [clamp(transformed[4] / viewport.width), clamp((transformed[5] - fontSize) / viewport.height), clamp((transformed[4] + width) / viewport.width), clamp(transformed[5] / viewport.height)];
  });
}

const union = (boxes) => [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])), Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))];

/**
 * The row and the column that run through a table cell, like Excel's Focus
 * Cell: the row band reaches left over the row name and the column band
 * reaches up over the column name, so the reader sees what the number means.
 * Returns null when the cell is not in a table of the page.
 */
export function cellBands(evidences, key, page, runs = []) {
  const cell = evidences.find((item) => item.evidence_key === key);
  const locator = cell?.table_locator;
  const box = clampBox(cell?.bbox);
  if (!box || !locator?.table_region_key || cell.page_number !== page) return null;
  const table = evidences.filter((item) => item.page_number === page && item.table_locator?.table_region_key === locator.table_region_key).map((item) => ({ item, box: clampBox(item.bbox) })).filter((entry) => entry.box);
  if (table.length < 4) return null;
  const extent = union(table.map((entry) => entry.box));
  const sameRow = table.filter((entry) => entry.item.table_locator.row_index === locator.row_index).map((entry) => entry.box);
  const sameColumn = table.filter((entry) => entry.item.table_locator.column_index === locator.column_index).map((entry) => entry.box);
  const rowY = union(sameRow.length ? sameRow : [box]);
  const columnX = union(sameColumn.length ? sameColumn : [box]);
  const middle = (b, axis) => (b[axis] + b[axis + 2]) / 2;
  // Line codes and note numbers are not cells, so the row name can sit far left of the first amount column.
  const rowName = runs.filter((b) => middle(b, 1) >= rowY[1] && middle(b, 1) <= rowY[3] && b[2] <= extent[0] + 0.01 && b[0] >= extent[0] - 0.8);
  const columnName = runs.filter((b) => middle(b, 0) >= columnX[0] - 0.01 && middle(b, 0) <= columnX[2] + 0.01 && b[3] <= extent[1] + 0.005 && b[1] >= extent[1] - 0.08);
  const left = Math.min(extent[0], ...rowName.map((b) => b[0]));
  const top = Math.min(extent[1], ...columnName.map((b) => b[1]));
  return { row: [left, rowY[1], extent[2], rowY[3]], column: [columnX[0], top, columnX[2], extent[3]] };
}
