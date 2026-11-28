// A table selection drawn as a chart that stays tied to its cells. Pure
// helpers: the card draws what these decide. Values are read from the current
// numbers every time, so a corrected cell moves its bar.
import { cellNumber, cellUnsure, periodRank } from "./cells.js";
import { clampBox } from "./pdfHighlight.js";
import { formatNumber, NOT_ADDITIVE, splitColumn, TOTAL_ROW, totalGroups } from "./reportChecks.js";

const isTotal = (cell) => TOTAL_ROW.test(String(cell.table_locator.row_header ?? "").trim());
const xMid = (cell) => { const box = clampBox(cell.bbox); return box ? (box[0] + box[2]) / 2 : cell.table_locator.column_index; };
// "- ĐMX": the dash marks a sub-item on the page; in a chart it is noise.
const rowName = (cell) => String(cell.table_locator.row_header ?? "").trim().replace(/^[-–•+]\s+/, "") || `Dòng ${cell.table_locator.row_index + 1}`;
const columnName = (cell) => String(cell.table_locator.column_header ?? "").trim() || `Cột ${cell.table_locator.column_index + 1}`;
// Columns in percent. Not the "do not add up" list: a price is not summed, but it is still an amount.
// "ratio" is left out: a current ratio of 1,5 is not 1,5%.
const PERCENT = /%|tỷ lệ|tỉ lệ|tỷ trọng|tỉ trọng|biên|margin|yoy|qoq/i;
// Numbers that already are a change: a percentage change of a change means nothing.
const CHANGE = /thay đổi|tăng trưởng|chênh lệch|growth|yoy|qoq|\+\/-/i;
// Letter lookarounds, not \b: \b treats "đ" and "ồ" as non-letters.
const AMOUNT = /(?<!\p{L})(vnd|usd|đồng|triệu|nghìn)(?!\p{L})/iu;
const headers = (cell) => `${cell.table_locator.column_header ?? ""} ${cell.table_locator.row_header ?? ""}`;
// A cell in percent, by its column or its row ("Biên lợi nhuận gộp" is a row of margins in an amount column).
const isRatio = (cell) => PERCENT.test(headers(cell)) && !AMOUNT.test(headers(cell));
// The length of a period, so quarters are only put in order with quarters.
const periodKind = (period) => { const text = String(period).toLowerCase(); return /9\s*m|9 tháng/.test(text) ? "9m" : /6\s*m|6 tháng|h[12]|nửa/.test(text) ? "6m" : /q|quý/.test(text) ? "q" : /tháng/.test(text) ? "m" : "y"; };
export const MAX_SERIES = 5;
const pct = (value) => `${formatNumber(Math.round(value * 10) / 10)}%`;

/**
 * The chart behind a selection, or null when there is nothing to compare.
 * Rows of the table stay rows of the chart (one group each, in page order);
 * columns become series, in time order when the headers say which came first.
 * One row across several columns turns around: the columns are the groups.
 */
export function chartData(keys, evidences, names = null) {
  const byKey = new Map((evidences ?? []).map((cell) => [cell.evidence_key, cell]));
  const found = (keys ?? []).map((key) => byKey.get(key)).filter((cell) => cell?.table_locator);
  // Keys are positions: after a re-read the same key can name another cell. Only cells that still carry the names saved with the chart are drawn.
  const picked = names ? found.filter((cell) => { const name = names[cell.evidence_key]; return !name || (name[0] === cell.table_locator.row_header && name[1] === cell.table_locator.column_header); }) : found;
  const moved = found.length - picked.length;
  if (!picked.length) return null;
  const { table_region_key: tableKey } = picked[0].table_locator;
  const page = picked[0].page_number;
  let cells = picked.filter((cell) => cell.table_locator.table_region_key === tableKey && cell.page_number === page);
  if (cells.filter((cell) => cellNumber(cell) != null).length < 2) return null;

  const notes = moved ? [`${moved} ô không còn khớp sau lần đọc lại nên không vẽ.`] : [];
  // A total next to its own parts squeezes every other bar into a sliver.
  const parts = cells.filter((cell) => !isTotal(cell));
  if (new Set(parts.map((cell) => cell.table_locator.row_index)).size >= 2 && parts.length < cells.length) {
    notes.push(`Không vẽ dòng tổng (${[...new Set(cells.filter(isTotal).map(rowName))].join(", ")}) để các dòng còn lại không bị lấn.`);
    cells = parts;
  }
  // The same for rows of percentages among rows of amounts: a margin of 20 next to revenue of 34.147 is an invisible bar.
  const ratioRows = cells.filter((cell) => isRatio(cell) && !PERCENT.test(cell.table_locator.column_header ?? ""));
  const amountCells = cells.filter((cell) => !isRatio(cell) && cellNumber(cell) != null);
  if (ratioRows.length && amountCells.length) {
    notes.push(`Không vẽ dòng tỷ lệ (${[...new Set(ratioRows.map(rowName))].join(", ")}) vì khác đơn vị với các dòng còn lại.`);
    cells = cells.filter((cell) => !ratioRows.includes(cell));
  }

  // A footnote column ("Chú thích: 7") holds reference numbers, not values.
  cells = cells.filter((cell) => !/^(chú thích|ghi chú|thuyết minh|notes?)$/i.test(String(cell.table_locator.column_header ?? "").trim()));
  const columns = new Map();
  for (const cell of cells) {
    const id = `${cell.table_locator.column_index}`;
    if (!columns.has(id)) columns.set(id, { id, label: columnName(cell), cells: [] });
    columns.get(id).cells.push(cell);
  }
  let series = [...columns.values()];
  const split = series.map((item) => splitColumn(item.label));
  const ranks = split.map((item) => periodRank(item.period));
  // Periods of one length only: a quarter next to nine months is not "earlier and later" of the same thing.
  const timeOrdered = series.length > 1 && ranks.every((rank) => rank != null) && new Set(ranks).size === ranks.length && new Set(split.map((item) => item.measure)).size === 1 && new Set(split.map((item) => periodKind(item.period))).size === 1;
  const placeX = (item) => item.cells.reduce((acc, cell) => acc + xMid(cell), 0) / item.cells.length;
  // The full header is kept: a label shortened to its period ("2026") no longer says it is a percentage.
  series = series.map((item, i) => ({ ...item, header: item.label, rank: ranks[i], x: placeX(item), period: split[i].period, measure: split[i].measure }))
    .sort((a, b) => (timeOrdered ? a.rank - b.rank : a.x - b.x));
  if (timeOrdered) series.forEach((item) => { if (item.period) item.label = item.period; });
  // One colour per column and never a repeat: past five the colours run out, so the rest is left out and said so.
  if (series.length > MAX_SERIES) {
    notes.push(`Chỉ vẽ ${MAX_SERIES} cột đầu (bỏ ${series.slice(MAX_SERIES).map((item) => item.label).join(", ")}). Chọn ít cột hơn để vẽ các cột khác.`);
    const dropped = new Set(series.slice(MAX_SERIES).map((item) => item.id));
    series = series.slice(0, MAX_SERIES);
    cells = cells.filter((cell) => !dropped.has(`${cell.table_locator.column_index}`));
  }

  // Percentages and amounts on one scale mislead: the percentage columns start hidden.
  // "Giá dự phóng theo tỷ trọng (VND)" names a currency: an amount, whatever else the header says.
  const ratio = (item) => item.cells.every(isRatio);
  // ...but only when the amounts left in view still have numbers to draw.
  const mixed = series.some(ratio) && series.some((item) => !ratio(item));
  const amountNumbers = series.filter((item) => !ratio(item)).flatMap((item) => item.cells).filter((cell) => cellNumber(cell) != null).length;
  const hidden = mixed && amountNumbers >= 1 ? series.filter(ratio).map((item) => item.id) : [];

  const rowIndexes = [...new Set(cells.map((cell) => cell.table_locator.row_index))].sort((a, b) => a - b);
  const bar = (cell, seriesId) => ({ key: cell.evidence_key, series: seriesId, value: cellNumber(cell), unsure: cellUnsure(cell), cell });
  // One row across columns of the same kind reads as columns in time; mixed units keep their own toggles.
  const turned = rowIndexes.length === 1 && series.length >= 2 && !mixed;
  const groups = turned
    ? series.map((item) => ({ id: item.id, label: item.label, bars: [bar(item.cells[0], "row")] }))
    : rowIndexes.map((row) => {
      const inRow = cells.filter((cell) => cell.table_locator.row_index === row);
      return { id: `${row}`, label: rowName(inRow[0]), bars: series.map((item) => inRow.find((cell) => `${cell.table_locator.column_index}` === item.id)).map((cell, i) => cell && bar(cell, series[i].id)).filter(Boolean) };
    });
  const shownSeries = turned ? [{ id: "row", label: rowName(cells[0]), ratio: series.every(ratio), measure: series[0].measure, kind: "y" }] : series.map((item) => ({ id: item.id, label: item.label, ratio: ratio(item), measure: item.measure, kind: periodKind(item.period) }));

  const tableCells = (evidences ?? []).filter((cell) => cell.table_locator?.table_region_key === tableKey && cell.page_number === page);
  const measure = series[0].measure && new Set(series.map((item) => item.measure)).size === 1 ? series[0].measure : "";
  const title = turned ? [rowName(cells[0]), measure].filter(Boolean).join(" · ") : timeOrdered ? series[0].measure || "So sánh theo kỳ" : series.length === 1 ? series[0].label : "So sánh các dòng đã chọn";
  // Numbers of a "%" column are already percentages: they are shown with the sign.
  const percent = series.filter((item) => !hidden.includes(item.id)).every(ratio);
  // Facts the takeaway needs to stay honest.
  const change = cells.every((cell) => CHANGE.test(headers(cell)));
  const hasTotal = cells.some(isTotal);
  // A quarter next to nine months: their sizes say nothing about each other.
  const mixedPeriods = new Set(series.map((item) => periodKind(item.period))).size > 1;
  return { change, hasTotal, mixedPeriods, keys: cells.map((cell) => cell.evidence_key), page, tableKey, title, percent, turned, timeOrdered, series: shownSeries, groups, hidden, notes, share: shareOf(groups, tableCells) };
}

/**
 * Each bar's share of the total row it adds up to, or null when any bar has
 * none: a share of some bars only would mix two kinds of number on one axis.
 */
function shareOf(groups, tableCells) {
  const totals = new Map();
  for (const { bars } of groups) {
    for (const { key, cell, value } of bars) {
      if (value == null) continue;
      if (NOT_ADDITIVE.test(cell.table_locator.column_header ?? "") || NOT_ADDITIVE.test(cell.table_locator.row_header ?? "")) return null;
      const column = tableCells.filter((other) => other.table_locator.column_index === cell.table_locator.column_index);
      const group = totalGroups(column).find((item) => item.parts.some((part) => part.evidence_key === key));
      const total = cellNumber(group?.total);
      const parts = group?.parts.map(cellNumber).filter((part) => part != null) ?? [];
      // A share means something only when every part pulls the same way.
      if (!total || !(parts.every((part) => part >= 0) || parts.every((part) => part <= 0))) return null;
      totals.set(key, total);
    }
  }
  return totals.size ? totals : null;
}

/** The number each bar shows: the cell itself, or its share of the total in percent. */
export const barValue = (bar, mode, share) => (bar.value == null ? null : mode === "share" && share?.has(bar.key) ? bar.value / share.get(bar.key) * 100 : bar.value);

/**
 * One or two sentences on what the chart shows, worked out from the numbers
 * themselves (no AI). It says nothing rather than something misleading:
 * - a percentage moves in points, never in percent of itself;
 * - numbers that already are changes ("+/-%YoY") get no change of their own;
 * - nothing has a percentage change from 0 or across a change of sign;
 * - two negative numbers (costs) are compared by size: −330 to −411 is a cost that grew;
 * - largest and smallest only among bars of one kind (one measure, one unit, no total row).
 */
export function chartTakeaway(data, { mode = "value", off = [] } = {}) {
  if (!data) return "";
  const on = (bar) => !off.includes(bar.series) && bar.value != null;
  const show = (value) => (mode === "share" ? pct(value) : `${formatNumber(Math.round(value * 100) / 100)}${data.percent ? "%" : ""}`);
  const seriesName = (id) => data.series.find((item) => item.id === id)?.label ?? "";
  const visible = data.series.filter((item) => !off.includes(item.id));
  // Percentages and amounts in view together: no sentence can compare them.
  if (visible.some((item) => item.ratio) && visible.some((item) => !item.ratio)) return "";
  const bars = data.groups.flatMap((group) => group.bars.filter(on).map((bar) => ({ ...bar, group: group.label, shown: barValue(bar, mode, data.share) })));
  if (bars.length < 2) return "";
  const points = visible.every((item) => item.ratio);
  const flip = (a, b) => (a < 0 && b > 0) || (a > 0 && b < 0);
  // How far a number moved: null when there is no fair way to say it.
  const moved = (a, b) => (points ? b - a : a === 0 || flip(a, b) ? null : a < 0 ? (Math.abs(b) - Math.abs(a)) / Math.abs(a) * 100 : (b - a) / a * 100);
  const size = (change) => (points ? `${formatNumber(Math.round(Math.abs(change) * 10) / 10)} điểm %` : pct(Math.abs(change)));
  const signed = (change) => `${change >= 0 ? "+" : "−"}${size(change)}`;
  const aside = (label, a, b) => (a < 0 && b < 0 ? `${label}: số âm, độ lớn ${Math.abs(b) > Math.abs(a) ? "tăng" : "giảm"} ${pct(Math.abs((Math.abs(b) - Math.abs(a)) / Math.abs(a) * 100))} (${show(a)} → ${show(b)}).` : `${label} từ ${show(a)} ${b > a ? "lên" : "xuống"} ${show(b)}.`);

  if (data.turned) {
    const [first, last] = [bars[0], bars.at(-1)];
    const top = bars.reduce((best, item) => (item.shown > best.shown ? item : best));
    let move = "";
    if (mode === "value" && data.timeOrdered && !data.change) {
      const span = `Từ ${first.group} đến ${last.group}`;
      const change = moved(first.shown, last.shown);
      move = first.shown === last.shown ? `${span} không đổi.`
        : first.shown < 0 && last.shown < 0 && !points ? aside(span, first.shown, last.shown)
        : change == null ? `${span}: từ ${show(first.shown)} ${last.shown > first.shown ? "lên" : "xuống"} ${show(last.shown)}.`
        : `${span} ${change > 0 ? "tăng" : "giảm"} ${size(change)}.`;
    }
    // With two bars the highest is plain to see; the sentence earns its place from three.
    return [move, bars.length >= 3 && !data.hasTotal && !data.mixedPeriods ? `Cao nhất ở ${top.group} (${show(top.shown)}).` : ""].filter(Boolean).join(" ");
  }
  if (data.timeOrdered && visible.length >= 2 && mode === "value" && !data.change) {
    const [from, to] = [visible[0].id, visible.at(-1).id];
    const span = `từ ${seriesName(from)} đến ${seriesName(to)}`;
    const pairs = data.groups.map((group) => ({ label: group.label, a: group.bars.find((bar) => bar.series === from)?.value, b: group.bars.find((bar) => bar.series === to)?.value })).filter((item) => item.a != null && item.b != null);
    // Rows that start at 0, change sign, or are negative are said on their own, first, and never counted in "cả N dòng".
    const apart = (item) => !points && (moved(item.a, item.b) == null || (item.a < 0 && item.b < 0));
    const odd = pairs.filter((item) => apart(item) && item.a !== item.b);
    const moves = pairs.filter((item) => !apart(item)).map((item) => ({ ...item, change: moved(item.a, item.b) }));
    const lead = odd.length > 2 ? [`${odd.length} dòng là số âm, từ 0 hoặc đổi dấu, xem từng cột.`] : odd.map((item) => aside(item.label, item.a, item.b));
    const say = (text) => [...lead, text].filter(Boolean).join(" ");
    if (!moves.length) return say("");
    const up = moves.reduce((best, item) => (item.change > best.change ? item : best));
    const down = moves.reduce((best, item) => (item.change < best.change ? item : best));
    const all = moves.length === 1 ? moves[0].label : odd.length ? `${moves.length} dòng còn lại` : `Cả ${moves.length} dòng`;
    if (moves.every((item) => item.change === 0)) return say(`${all} không đổi ${span}.`);
    if (moves.length === 1) return say(`${all} ${up.change > 0 ? "tăng" : "giảm"} ${size(up.change)} ${span}.`);
    if (moves.every((item) => item.change > 0)) return say(`${all} đều tăng ${span}, mạnh nhất là ${up.label} (${signed(up.change)}).`);
    if (moves.every((item) => item.change < 0)) return say(`${all} đều giảm ${span}, mạnh nhất là ${down.label} (${signed(down.change)}).`);
    return say([up.change > 0 && `Tăng mạnh nhất ${span}: ${up.label} (${signed(up.change)}).`, down.change < 0 && `Giảm mạnh nhất: ${down.label} (${signed(down.change)}).`].filter(Boolean).join(" "));
  }
  // Largest and smallest only among like things: one measure, one length of period, and no total next to its parts.
  if (data.hasTotal || new Set(visible.map((item) => item.measure ?? "")).size > 1 || new Set(visible.map((item) => item.kind ?? "y")).size > 1) return "";
  const name = (bar) => (data.series.length > 1 ? `${bar.group} (${seriesName(bar.series)})` : bar.group);
  const top = bars.reduce((best, item) => (item.shown > best.shown ? item : best));
  const low = bars.reduce((best, item) => (item.shown < best.shown ? item : best));
  if (top.shown === low.shown) return `Các cột bằng nhau: ${show(top.shown)}.`;
  return mode === "share" ? `${name(top)} chiếm nhiều nhất: ${show(top.shown)}.` : `Lớn nhất: ${name(top)}, ${show(top.shown)}. Nhỏ nhất: ${name(low)}, ${show(low.shown)}.`;
}

/** Round axis steps (1, 2, 2,5 or 5 × 10ⁿ) that cover the range and always include 0. */
export function niceTicks(min, max, count = 5) {
  const low = Math.min(0, min);
  const high = Math.max(0, max);
  if (high === low) return [0, 1];
  const raw = (high - low) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((value) => value >= raw);
  const ticks = [];
  for (let value = Math.floor(low / step) * step; value <= high + step * 1e-9; value += step) ticks.push(Math.round(value / step) * step);
  if (ticks.at(-1) < high) ticks.push(ticks.at(-1) + step);
  return ticks;
}

/** An axis label: in full below ten million, then in words ("1,2 tỷ"). */
export function axisNumber(value, percent = false) {
  if (percent) return `${formatNumber(value)}%`;
  const abs = Math.abs(value);
  const short = (divisor, word) => `${formatNumber(Math.round(value / divisor * 10) / 10)} ${word}`;
  if (abs >= 1e9) return short(1e9, "tỷ");
  if (abs >= 1e7) return short(1e6, "triệu");
  return formatNumber(value);
}

// Charts the reader made, per report, kept in this browser only.
const STORE_KEY = "sourcelens-charts-v1";
export const MAX_CHARTS = 6;

export function loadCharts(reportId) {
  try { const all = JSON.parse(localStorage.getItem(STORE_KEY) ?? "{}"); return Array.isArray(all[reportId]) ? all[reportId] : []; } catch { return []; }
}

export function saveCharts(reportId, charts) {
  try {
    const all = JSON.parse(localStorage.getItem(STORE_KEY) ?? "{}");
    if (charts.length) all[reportId] = charts.slice(-MAX_CHARTS); else delete all[reportId];
    localStorage.setItem(STORE_KEY, JSON.stringify(all));
  } catch { /* private mode: charts last until the page closes */ }
}
