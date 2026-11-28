// Table cells as things you can tap, select, explain and check. Pure helpers:
// the PDF page draws them, these decide what they mean.
import { evidenceLabel, needsCheck } from "./format.js";
import { clampBox } from "./pdfHighlight.js";
import { byTime, checkTableTotals, columnParents, formatNumber, isTotalName, NOT_ADDITIVE, periodRank, periodWords, rowWords, splitColumn, totalGroups } from "./reportChecks.js";

export { periodRank };

export const cellNumber = (cell) => (cell?.current_numeric_value == null ? null : Number(cell.current_numeric_value));
const isTotalRow = (cell) => isTotalName(cell?.table_locator?.row_header);
// Where a cell sits across the page: the eye's column, which survives blank or merged cells better than column_index.
const xMid = (cell) => { const box = clampBox(cell.bbox); return box ? (box[0] + box[2]) / 2 : cell.table_locator.column_index; };
const pct = (value) => `${formatNumber(Math.round(value * 100) / 100)}%`;

/**
 * A cell that holds a number, or a short mark standing in for one ("—", "n/a").
 * Prose in a notes column is a table cell to the extractor but not something to tap or flag.
 */
export const isNumberCell = (cell) => {
  if (cell?.current_numeric_value != null) return true;
  const raw = String(cell?.raw_text ?? "").replace(/\s/g, "");
  // A long reading made only of digits and marks ("(487,478,693)") is still a number the reader could not settle.
  return /^[\d.,()%+\-−–—~;:]+$/.test(raw) || (raw.length <= 12 && !/\p{L}{4,}/u.test(raw));
};

/** A cell the reader cannot vouch for: unclear reading, or a corrected value it has not re-read. */
export const cellUnsure = (cell) => needsCheck(cell?.data_status) && cell?.current_numeric_value === cell?.original_numeric_value;

/**
 * The tables of one page, each as rows of cells in reading order. Only cells
 * with a box are kept, because a cell you cannot see you cannot tap.
 */
export function pageTables(evidences, page) {
  const byTable = new Map();
  for (const cell of evidences ?? []) {
    const locator = cell.table_locator;
    if (!locator?.table_region_key || cell.page_number !== page || !clampBox(cell.bbox) || !isNumberCell(cell)) continue;
    if (!byTable.has(locator.table_region_key)) byTable.set(locator.table_region_key, []);
    byTable.get(locator.table_region_key).push(cell);
  }
  return [...byTable].map(([key, cells]) => {
    const rowIndexes = [...new Set(cells.map((cell) => cell.table_locator.row_index))].sort((a, b) => a - b);
    const rows = rowIndexes.map((row) => cells.filter((cell) => cell.table_locator.row_index === row).sort((a, b) => xMid(a) - xMid(b)));
    return { key, rows, cells };
  });
}

/** Two cells of one measure in time order, with their period names; page order when the headers do not say. */
export function inTimeOrder(a, b) {
  const [pa, pb] = [a, b].map((cell) => splitColumn(cell.table_locator?.column_header).period);
  const [ra, rb] = [pa, pb].map(periodRank);
  const swap = ra != null && rb != null && ra !== rb ? ra > rb : xMid(a) > xMid(b);
  const [first, second] = swap ? [b, a] : [a, b];
  const name = (cell) => splitColumn(cell.table_locator?.column_header).period || cell.table_locator?.column_header || "";
  return { first, second, from: name(first), to: name(second) };
}

/** The cell an arrow key moves to, staying inside the table; null at the edge. */
export function neighbourCell(table, key, dx, dy) {
  const here = table.cells.find((cell) => cell.evidence_key === key);
  if (!here) return null;
  const rowAt = table.rows.findIndex((row) => row.includes(here));
  if (dy) {
    const row = table.rows[rowAt + dy];
    if (!row) return null;
    const x = xMid(here);
    return row.reduce((best, cell) => (Math.abs(xMid(cell) - x) < Math.abs(xMid(best) - x) ? cell : best), row[0]);
  }
  const row = table.rows[rowAt];
  return row[row.indexOf(here) + dx] ?? null;
}

/** Every cell in the rectangle spanned by two cells of one table (Shift+click, Shift+arrows, drag). */
export function cellRange(table, fromKey, toKey) {
  const from = table.cells.find((cell) => cell.evidence_key === fromKey);
  const to = table.cells.find((cell) => cell.evidence_key === toKey);
  if (!from || !to) return [];
  const [r0, r1] = [from.table_locator.row_index, to.table_locator.row_index].sort((a, b) => a - b);
  // Columns by position on the page: a cell is in when its middle lies between the outer edges
  // of the two end cells, so a narrow "—" counts next to wider numbers.
  const edges = [from, to].map((cell) => clampBox(cell.bbox));
  const x0 = edges.every(Boolean) ? Math.min(edges[0][0], edges[1][0]) : Math.min(xMid(from), xMid(to));
  const x1 = edges.every(Boolean) ? Math.max(edges[0][2], edges[1][2]) : Math.max(xMid(from), xMid(to));
  return table.cells.filter((cell) => cell.table_locator.row_index >= r0 && cell.table_locator.row_index <= r1 && xMid(cell) >= x0 && xMid(cell) <= x1).map((cell) => cell.evidence_key);
}

const sameTable = (cell, evidences) => (evidences ?? []).filter((other) => other.table_locator?.table_region_key === cell.table_locator?.table_region_key && other.page_number === cell.page_number);

/**
 * Why a cell is what it is, in plain sentences: how it moved against the
 * other period of the same measure, against the whole table, and its share
 * and rank in its column. Only what the table itself can show.
 */
export function explainCell(cell, evidences) {
  const value = cellNumber(cell);
  if (value == null || !cell.table_locator) return [];
  const table = sameTable(cell, evidences);
  const { row_index: row, column_index: column } = cell.table_locator;
  const inColumn = (index) => table.filter((other) => other.table_locator.column_index === index);
  // This cell's group: the total row it adds up to, or, for a total, the rows it adds up.
  const same = (other) => other.evidence_key === cell.evidence_key;
  const group = totalGroups(inColumn(column)).filter((item) => item.status === "ok" || item.status === "bad").find((item) => same(item.total) || item.parts.some(same));
  // Rows under a heading or subtotal ("111" and "112" under "I. Tiền") are measured against that row.
  const parents = columnParents(inColumn(column));
  const parent = parents.get(cell.evidence_key);
  const whole = group && group.parts.some(same) ? group
    : parent ? { total: parent, parts: inColumn(column).filter((other) => parents.get(other.evidence_key) === parent) } : null;
  const lines = [];

  if (isTotalRow(cell)) {
    // Same rules as the summary's own check (rounding, % columns, missing rows), so the two never disagree.
    const check = checkTableTotals(table).find((item) => item.keys[0] === cell.evidence_key);
    if (check?.ok) lines.push({ text: Math.abs(check.diff) > 1e-9
      ? `Tổng ${check.count} dòng · khớp (làm tròn)`
      : `Tổng ${check.count} dòng · khớp` });
    else if (check) lines.push({ text: `Tổng ${check.count} dòng · lệch ${formatNumber(Math.abs(check.diff))}`, bad: true });
  }

  // The other period of the same measure in this row, e.g. Quý 1 next to Quý 2.
  const { measure, period } = splitColumn(cell.table_locator.column_header);
  if (period) {
    const sibling = table.filter((other) => other.table_locator.row_index === row && other.table_locator.column_index !== column && cellNumber(other) != null)
      .filter((other) => { const split = splitColumn(other.table_locator.column_header); return split.measure === measure && split.period && split.period !== period; })
      .sort((a, b) => Math.abs(a.table_locator.column_index - column) - Math.abs(b.table_locator.column_index - column))[0];
    if (sibling) {
      // Earlier period first, by what the headers say, not by where the column sits.
      const before = inTimeOrder(sibling, cell).first === sibling;
      const [from, to] = before ? [cellNumber(sibling), value] : [value, cellNumber(sibling)];
      const [fromName, toName] = before ? [splitColumn(sibling.table_locator.column_header).period, period] : [period, splitColumn(sibling.table_locator.column_header).period];
      // The same total row in both periods, so a subtotal is compared with its own subtotal.
      const totalIn = (index) => group && !isTotalRow(cell) ? table.find((other) => other.table_locator.column_index === index && other.table_locator.row_index === group.total.table_locator.row_index) : null;
      const totalFrom = totalIn((before ? sibling : cell).table_locator.column_index);
      const totalTo = totalIn((before ? cell : sibling).table_locator.column_index);
      if (from === 0 && to > 0) lines.push({ text: `${fromName} là 0, ${toName} là ${formatNumber(to)}: mới phát sinh trong ${toName}.`, unusual: true });
      else if (from) {
        const growth = (to - from) / Math.abs(from) * 100;
        let text = `${fromName} → ${toName} ${growth >= 0 ? "tăng" : "giảm"} ${pct(Math.abs(growth))}`;
        let unusual = false;
        if (cellNumber(totalFrom) && cellNumber(totalTo) != null) {
          const all = (cellNumber(totalTo) - cellNumber(totalFrom)) / Math.abs(cellNumber(totalFrom)) * 100;
          const gap = growth - all;
          text += `, ${Math.abs(gap) < 3 ? "gần bằng" : gap > 0 ? "cao hơn" : "thấp hơn"} cả bảng (${pct(all)})`;
          unusual = Math.abs(gap) >= 10;
        }
        lines.push({ text: `${text}.`, unusual });
      }
    }
  }

  // Share and rank only where they mean something: an additive column whose parts all have the same sign.
  const parts = whole ? whole.parts.filter((other) => cellNumber(other) != null) : [];
  const sameSign = parts.every((other) => cellNumber(other) >= 0) || parts.every((other) => cellNumber(other) <= 0);
  if (parts.length >= 2 && sameSign && cellNumber(whole.total) && !NOT_ADDITIVE.test(cell.table_locator.column_header ?? "")) {
    const rank = [...parts].sort((a, b) => cellNumber(b) - cellNumber(a)).findIndex(same) + 1;
    const of = whole === group ? "" : ` của ${rowWords(whole.total.table_locator.row_header) || "dòng trên"}`;
    lines.push({ text: `Chiếm ${pct(value / cellNumber(whole.total) * 100)}${of} · thứ ${rank}/${parts.length}` });
  }
  return lines;
}

/** The answers that use a cell, as a quote, an input of a calculation, or both. */
export function answersUsingCell(key, notes) {
  return (notes ?? []).filter((note) => {
    const answer = note.reply?.structured_answer;
    if (!answer) return false;
    return (answer.evidence ?? []).some((item) => item.evidence_key === key) || (answer.formulas ?? []).some((formula) => (formula.inputs ?? []).some((input) => input.evidence_key === key));
  }).map((note) => ({ id: note.id, question: note.question?.body ?? "" }));
}

/**
 * What a selection adds up to, plus the ways a quick sum can mislead: a number the
 * reader is unsure about, and a row added together with the total or subtotal it is
 * part of. all is every cell of the page, so the selection is read against its columns.
 */
export function summarizeSelection(cells, all = cells) {
  const numbers = cells.map(cellNumber).filter((value) => value != null);
  if (!numbers.length) return null;
  const sum = numbers.reduce((acc, value) => acc + value, 0);
  const caveats = [];
  const unsure = cells.filter(cellUnsure).length;
  if (unsure) caveats.push(`${unsure} số có thể sai`);
  const skipped = cells.length - numbers.length;
  if (skipped) caveats.push(`${skipped} ô trống`);
  if (countsTwice(cells, all)) caveats.push("gồm dòng tổng, bị cộng trùng");
  // A sum of percentages or ratios means nothing; neither does one across different measures.
  const headers = cells.map((cell) => cell.table_locator?.column_header ?? "");
  // A ratio shows in its header ("Biên lợi nhuận") or in the cells themselves ("+12,1%" under "Thay đổi").
  const additive = !headers.some((header) => NOT_ADDITIVE.test(header))
    && !cells.some((cell) => String(cell.raw_text ?? "").includes("%") || cell.semantic?.unit === "PERCENT");
  if (!additive) caveats.push("cột tỷ lệ, cộng lại không có nghĩa");
  // "Số cuối kỳ" next to "Số đầu năm" are two periods of one measure, not two measures.
  if (new Set(headers.map((header) => splitColumn(header).measure).filter(Boolean)).size > 1) caveats.push("gồm nhiều chỉ tiêu khác nhau");
  // A change only reads right between two periods of one row, earlier to later.
  const pair = cells.filter((cell) => cellNumber(cell) != null);
  const oneRow = pair.length === 2 && pair[0].table_locator && pair[1].table_locator && pair[0].table_locator.table_region_key === pair[1].table_locator.table_region_key && pair[0].table_locator.row_index === pair[1].table_locator.row_index;
  const order = oneRow ? inTimeOrder(pair[0], pair[1]) : null;
  const start = order && cellNumber(order.first);
  const change = order && start ? (cellNumber(order.second) - start) / Math.abs(start) * 100 : null;
  return { count: numbers.length, sum, additive, average: sum / numbers.length, max: Math.max(...numbers), change, changeFrom: order?.from ?? "", changeTo: order?.to ?? "", caveats };
}

/** True when a picked row adds into another picked row of its column: the same money counted twice. */
function countsTwice(cells, all) {
  const picked = new Set(cells.map((cell) => cell.evidence_key));
  const columnKey = (cell) => `${cell.page_number}::${cell.table_locator?.table_region_key}::${cell.table_locator?.column_index}`;
  const columns = new Map();
  for (const cell of cells) {
    if (!cell.table_locator || columns.has(columnKey(cell))) continue;
    const column = [...new Map([...all, ...cells].filter((other) => other.table_locator && columnKey(other) === columnKey(cell)).map((other) => [other.evidence_key, other])).values()];
    columns.set(columnKey(cell), columnParents(column));
  }
  return cells.some((cell) => {
    const parents = columns.get(columnKey(cell));
    for (let up = parents?.get(cell.evidence_key), guard = 0; up && guard < 50; up = parents.get(up.evidence_key), guard += 1) if (picked.has(up.evidence_key)) return true;
    // A total row under any picked row of its column, even when the rows do not add up to it.
    return isTotalRow(cell) && cells.some((part) => part !== cell && !isTotalRow(part) && part.table_locator && columnKey(part) === columnKey(cell) && part.table_locator.row_index < cell.table_locator.row_index);
  });
}

const listWords = (items) => (items.length <= 2 ? items.join(" và ") : `${items.slice(0, -1).join(", ")} và ${items.at(-1)}`);

/**
 * Up to three questions about a selection, written out in full so the AI
 * knows exactly which cells are meant. Growth from zero asks for the change,
 * never a percentage. Rows without names still get a question, by their values.
 */
export function selectionQuestions(cells, evidences = cells) {
  const withValue = cells.filter((cell) => cellNumber(cell) != null && cell.table_locator);
  if (withValue.length < 2) return [];
  const rows = [...new Set(withValue.filter((cell) => !isTotalRow(cell)).map((cell) => rowWords(cell.table_locator.row_header)).filter(Boolean))];
  const columns = [...new Set([...withValue].sort((a, b) => xMid(a) - xMid(b)).map((cell) => cell.table_locator.column_header).filter(Boolean))];
  const questions = [];
  const split = columns.map(splitColumn);
  // A column that names only a period ("Số cuối kỳ") is said as a time: "cuối kỳ".
  if (rows.length >= 2 && columns.length === 1) questions.push(split[0].measure ? `Trong ${columns[0]}, mục nào cao nhất giữa ${listWords(rows)}?` : `Mục nào cao nhất ${periodWords(split[0].period)} giữa ${listWords(rows)}?`);
  const periods = byTime(split.filter((item) => item.period && item.measure === split[0].measure));
  if (periods.length >= 2 && rows.length) {
    const first = withValue.filter((cell) => splitColumn(cell.table_locator.column_header).period === periods[0].period);
    const fromZero = first.some((cell) => cellNumber(cell) === 0);
    const [from, to] = split[0].measure ? [periods[0].period, periods.at(-1).period] : [periodWords(periods[0].period), periodWords(periods.at(-1).period)];
    questions.push(`${split[0].measure ? `${split[0].measure} của ` : ""}${listWords(rows)} ${fromZero ? "tăng bao nhiêu" : "tăng bao nhiêu phần trăm"} từ ${from} đến ${to}?`);
  }
  // A share question only when the table has a total row to divide by.
  const lastColumn = withValue.find((cell) => cell.table_locator.column_header === columns.at(-1))?.table_locator.column_index;
  const hasTotal = sameTable(withValue[0], evidences).some((cell) => isTotalRow(cell) && cell.table_locator.column_index === lastColumn && cellNumber(cell));
  if (rows.length && hasTotal && columns.length) questions.push(`${rows[0]} chiếm bao nhiêu phần trăm tổng ${split.at(-1).measure ? columns.at(-1) : periodWords(split.at(-1).period)}?`);
  if (!rows.length) {
    const values = withValue.slice(0, 4).map((cell) => formatNumber(cellNumber(cell)));
    questions.push(`Các số ${listWords(values)}${withValue.length > 4 ? "…" : ""} ở trang ${withValue[0].page_number} là của mục nào?`);
  }
  return questions.filter((question) => question.length <= 160).slice(0, 3);
}

/**
 * Why a swapped-in cell may not fit the calculation, compared with the cell it
 * replaces: a total for a single row (or the other way round), or another
 * measure. Empty when it is a like-for-like swap.
 */
export function pickWarning(oldCell, newCell) {
  if (!oldCell?.table_locator || !newCell?.table_locator) return "";
  // Short enough for one line of the bar: the reader sees why before choosing.
  if (isTotalRow(oldCell) !== isTotalRow(newCell)) {
    return isTotalRow(newCell) ? "Ô mới là dòng tổng, ô cũ là dòng chi tiết." : "Ô mới là dòng chi tiết, ô cũ là dòng tổng.";
  }
  const [was, now] = [oldCell, newCell].map((cell) => splitColumn(cell.table_locator.column_header).measure);
  if (was && now && was !== now) return `Ô mới thuộc chỉ tiêu khác (${now}, không phải ${was}).`;
  return "";
}

/** Cells worth suggesting in place of one input: the same row or column of its table, with a number. */
export function pickCandidates(cell, evidences, skip = []) {
  if (!cell?.table_locator) return [];
  return sameTable(cell, evidences).filter((other) => cellNumber(other) != null && other.evidence_key !== cell.evidence_key && !skip.includes(other.evidence_key)
    && (other.table_locator.row_index === cell.table_locator.row_index || Math.abs(xMid(other) - xMid(cell)) < 0.01));
}

/** A cell's name for buttons, labels and announcements. */
export const cellName = (cell) => evidenceLabel(cell) || `${cell?.table_locator ? "Ô" : "Số"} ở trang ${cell?.page_number}`;

const readingOrder = (cells) => {
  const line = (cell) => { const box = clampBox(cell.bbox); return Math.round((box[1] + box[3]) / 2 * 150); };
  return cells.sort((a, b) => line(a) - line(b) || clampBox(a.bbox)[0] - clampBox(b.bbox)[0]);
};

/**
 * The numbers read from the page's running text (not tables or charts), in
 * reading order: line by line from the top, left to right in a line.
 */
export function pageProse(evidences, page) {
  return readingOrder(evidences.filter((cell) => cell.source_type === "text" && !cell.table_locator && cell.page_number === page && clampBox(cell.bbox) && isNumberCell(cell)));
}

// Chart values with a box of their own (a printed label or a bar). A value boxed by the whole chart would be one huge tap target.
const OWN_CHART_BOX = new Set(["box_printed_label", "box_bar", "box_point", "geometry_printed_label_match", "native_printed_label_match", "vlm_printed_label_bbox_approximate"]);

/** The chart values of the page that have their own box on it, in reading order. */
export function pageChartLabels(evidences, page) {
  return readingOrder(evidences.filter((cell) => (cell.source_type === "chart" || cell.chart_read) && !cell.table_locator && cell.page_number === page && clampBox(cell.bbox) && cell.current_numeric_value != null
    && (cell.chart_read?.assumptions ?? []).some((tag) => OWN_CHART_BOX.has(tag))));
}

const SENTENCE_END = /[.!?;](?=\s)|\n/g;
/**
 * The sentence of a paragraph that holds the characters start..end, split
 * around them: { before, number, after }. Long sides are cut at a word with "…".
 */
export function sentenceAround(text, start, end, room = 110) {
  if (typeof text !== "string" || !(start >= 0) || !(end > start) || end > text.length) return null;
  let from = 0;
  let to = text.length;
  for (const match of text.matchAll(SENTENCE_END)) {
    if (match.index < start) from = match.index + 1;
    else if (match.index >= end) { to = match.index + 1; break; }
  }
  let before = text.slice(from, start).trimStart();
  let after = text.slice(end, to).trimEnd();
  if (before.length > room) before = `…${before.slice(before.length - room).replace(/^\S*\s/, "")}`;
  if (after.length > room) after = `${after.slice(0, room).replace(/\s\S*$/, "")}…`;
  return { before, number: text.slice(start, end), after };
}
