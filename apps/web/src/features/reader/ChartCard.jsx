import { useEffect, useMemo, useRef, useState } from "react";
import { axisNumber, barValue, chartData, chartTakeaway, niceTicks } from "./charts.js";
// Okabe-Ito blue, bluish green, reddish purple, sky blue and orange, in this fixed order (checked for colour-blind separation).
// The first four match the calculation inputs. Five at most: charts.js leaves further columns out instead of repeating a colour.
const CHART_COLORS = ["#0072B2", "#009E73", "#CC79A7", "#56B4E9", "#E69F00"];
const partColor = (index) => CHART_COLORS[Math.min(index, CHART_COLORS.length - 1)];
import { formatNumber } from "./reportChecks.js";

const CHAR = 6.6; // average width of one 11 px Plex Sans character
// Cut from the middle: names in one table often share a start ("Doanh thu · Quý 1", "Doanh thu · Quý 2") and differ at the end.
const fit = (text, room) => {
  const max = Math.max(3, Math.floor(room / CHAR));
  if (text.length <= max) return text;
  const head = Math.max(1, Math.floor((max - 1) * 0.4));
  return `${text.slice(0, head)}…${text.slice(text.length - (max - 1 - head))}`;
};
const coarse = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(pointer: coarse)").matches);
const show = (value, share, percent = false) => (value == null ? "—" : share ? `${formatNumber(Math.round(value * 10) / 10)}%` : `${formatNumber(Math.round(value * 100) / 100)}${percent ? "%" : ""}`);

/** A bar with a 4 px round end at the data side and a square end at the baseline. */
function barPath(x0, x1, y, h, vertical) {
  if (vertical) {
    // x0..x1 are the left and right edges; y is the baseline, h the signed height (up is negative).
    const r = Math.min(4, Math.abs(h), (x1 - x0) / 2);
    const top = y + h;
    return h <= 0
      ? `M${x0},${y}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x1 - r}Q${x1},${top} ${x1},${top + r}V${y}Z`
      : `M${x0},${y}V${top - r}Q${x0},${top} ${x0 + r},${top}H${x1 - r}Q${x1},${top} ${x1},${top - r}V${y}Z`;
  }
  const r = Math.min(4, Math.abs(x1 - x0), h / 2);
  return x1 >= x0
    ? `M${x0},${y}H${x1 - r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 - r},${y + h}H${x0}Z`
    : `M${x0},${y}H${x1 + r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 + r},${y + h}H${x0}Z`;
}

/**
 * Where every mark goes. Table rows read as horizontal bars, like the table
 * itself; one row across periods reads as columns left to right in time.
 */
function layout(data, { width, mode, off, touch }) {
  const share = mode === "share";
  const percent = share || data.percent;
  const seriesOn = data.series.filter((item) => !off.includes(item.id));
  const groups = data.groups.map((group) => ({ ...group, bars: group.bars.filter((bar) => !off.includes(bar.series)) })).filter((group) => group.bars.length);
  const values = groups.flatMap((group) => group.bars.map((bar) => barValue(bar, mode, data.share))).filter((value) => value != null);
  // Columns in view with no number at all still get an axis, never NaN coordinates.
  if (!values.length) values.push(0);
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const [t0, t1] = [ticks[0], ticks.at(-1)];
  const color = (id) => partColor(Math.max(0, data.series.findIndex((item) => item.id === id)));
  const marks = [];

  // Columns only while every period name fits under its column; otherwise the same bars lie down, where names have room.
  const columnLeft = Math.max(...ticks.map((tick) => axisNumber(tick, percent).length)) * CHAR + 8;
  const columnSlot = (width - columnLeft - 4) / groups.length;
  if (data.turned && groups.every((group) => group.label.length * CHAR + 6 <= columnSlot)) {
    const left = columnLeft;
    const top = 18;
    const plot = 150;
    const height = top + plot + 22;
    const slot = columnSlot;
    const y = (value) => top + plot * (1 - (value - t0) / (t1 - t0));
    // Numbers never touch: the highest, the first and the last are written first, then any other that has room. The tip and the table carry the rest.
    const half = (i) => (show(barValue(groups[i].bars[0], mode, data.share), share, data.percent).length * CHAR) / 2 + 3;
    const middle = (i) => left + i * slot + slot / 2;
    const shownValues = groups.map((group) => barValue(group.bars[0], mode, data.share) ?? -Infinity);
    const peak = shownValues.indexOf(Math.max(...shownValues));
    const order = [...new Set([peak, 0, groups.length - 1, ...groups.map((_, i) => i)])];
    const kept = [];
    for (const i of order) if (kept.every((j) => Math.abs(middle(i) - middle(j)) >= half(i) + half(j))) kept.push(i);
    const named = (i) => kept.includes(i);
    groups.forEach((group, i) => {
      const bar = group.bars[0];
      const value = barValue(bar, mode, data.share);
      const w = Math.min(24, slot * 0.6);
      const x0 = left + i * slot + (slot - w) / 2;
      marks.push({ ...bar, group: group.label, value, color: color(bar.series), d: value == null ? null : barPath(x0, x0 + w, y(0), y(value) - y(0), true),
        hit: { x: left + i * slot + 1, y: top, w: slot - 2, h: plot }, label: { hidden: !named(i), x: x0 + w / 2, y: value == null ? y(0) - 4 : Math.min(y(0), y(value)) - 4, anchor: "middle" },
        name: { x: left + i * slot + slot / 2, y: height - 6, text: fit(group.label, slot - 4), anchor: "middle" } });
    });
    return { height, marks, grid: ticks.map((tick) => ({ x1: left, x2: width, y1: y(tick), y2: y(tick), zero: tick === 0, label: axisNumber(tick, percent), lx: left - 6, ly: y(tick) + 4, anchor: "end" })), seriesOn };
  }

  const longest = Math.max(...groups.map((group) => group.label.length));
  const left = Math.min(width * 0.4, Math.max(64, longest * CHAR + 16));
  const right = Math.max(...values.map((value) => show(value, share, data.percent).length)) * CHAR + 18;
  // Each bar row is at least 24 px to hit (WCAG 2.5.8), more under a finger.
  const thick = touch ? 26 : 22;
  const gap = 2;
  const band = seriesOn.length * thick + (seriesOn.length - 1) * gap;
  const top = 4;
  const x = (value) => left + (width - left - right) * (value - t0) / (t1 - t0);
  let at = top;
  groups.forEach((group) => {
    group.bars.forEach((bar) => {
      const slot = seriesOn.findIndex((item) => item.id === bar.series);
      const y0 = at + slot * (thick + gap);
      const value = barValue(bar, mode, data.share);
      const end = value == null ? x(0) : x(value);
      // A negative bar has its number at its own end when there is room, else right of the zero line.
      const text = show(value, share, data.percent).length * CHAR;
      const outside = value < 0 && end - 5 - text >= left;
      marks.push({ ...bar, group: group.label, value, color: color(bar.series), d: value == null ? null : barPath(x(0), end, y0, thick, false),
        hit: { x: left - 4, y: y0 - 1, w: width - left + 4, h: thick + gap }, label: outside ? { x: end - 5, y: y0 + thick / 2 + 4, anchor: "end" } : { x: Math.max(x(0), end) + 5, y: y0 + thick / 2 + 4, anchor: "start" } });
    });
    marks.push({ groupLabel: true, key: `g-${group.id}`, text: fit(group.label, left - 10), full: group.label, x: left - 8, y: at + band / 2 + 4 });
    at += band + 12;
  });
  const height = at - 12 + 24;
  // Labels side by side must not touch: on a narrow card only every second or third step is named.
  const room = (width - left - right) / Math.max(1, ticks.length - 1);
  const every = Math.ceil((Math.max(...ticks.map((tick) => axisNumber(tick, percent).length)) * CHAR + 8) / room);
  return { height, marks, grid: ticks.map((tick, i) => ({ named: i % every === 0, x1: x(tick), x2: x(tick), y1: top - 2, y2: at - 10, zero: tick === 0, label: axisNumber(tick, percent), lx: x(tick), ly: height - 6, anchor: "middle" })), seriesOn };
}

/**
 * A chart drawn from cells the reader selected. Every bar is its cell: hover
 * or focus outlines the cell on the page, Enter or a click opens it there.
 */
export function ChartCard({ chart, evidences, loading = false, activeKey, onPeek, onOpenCell, onShowCells, onChange, onRemove }) {
  const data = useMemo(() => chartData(chart.keys, evidences, chart.names), [chart.keys, chart.names, evidences]);
  const box = useRef(null);
  const [width, setWidth] = useState(320);
  const [at, setAt] = useState(0);
  const [hover, setHover] = useState(null);
  // Why a click did nothing, in words on screen (a tooltip never reaches touch or screen readers).
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const node = box.current;
    if (!node || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => setWidth(Math.max(240, Math.floor(node.clientWidth))));
    observer.observe(node);
    return () => observer.disconnect();
  }, [Boolean(data)]);

  if (!data && loading) {
    return <article id={`chart-${chart.id}`} tabIndex={-1} className="rd-card rd-chart" aria-busy="true">
      <span className="rd-kicker">Biểu đồ</span>
      <p className="rd-chart-take">Đang tải…</p>
    </article>;
  }
  if (!data) {
    return <article id={`chart-${chart.id}`} tabIndex={-1} className="rd-card rd-chart">
      <span className="rd-kicker">Biểu đồ</span>
      <p>Biểu đồ không còn dữ liệu</p>
      <button type="button" className="rd-button" onClick={() => onRemove(chart.id)}>Xóa</button>
    </article>;
  }

  const off = (chart.off ?? data.hidden).filter((id) => data.series.some((item) => item.id === id && !data.turned));
  const mode = chart.mode === "share" && data.share ? "share" : "value";
  const share = mode === "share";
  const touch = coarse();
  const plan = layout(data, { width, mode, off, touch });
  const bars = plan.marks.filter((mark) => !mark.groupLabel);
  const seriesName = (id) => (data.turned ? "" : data.series.find((item) => item.id === id)?.label ?? "");
  const describe = (bar) => [bar.group, seriesName(bar.series)].filter(Boolean).join(" · ");
  // How to use the bars is said once, on the chart; each bar says only what it is.
  const spoken = (bar) => `${describe(bar)}: ${bar.value == null ? "không có số" : show(bar.value, share, data.percent)}${bar.unsure ? ", có thể sai" : ""}`;
  const current = Math.min(at, bars.length - 1);
  const lit = hover ?? null;
  const tip = lit && bars.find((bar) => bar.key === lit);
  const takeaway = chartTakeaway(data, { mode, off });
  const unsure = bars.filter((bar) => bar.unsure).length;
  // Hiding is refused when it would leave no number in view; the button says why.
  const leavesNumbers = (next) => data.groups.some((group) => group.bars.some((bar) => !next.includes(bar.series) && bar.value != null));
  const toggle = (id) => {
    const next = off.includes(id) ? off.filter((item) => item !== id) : [...off, id];
    if (leavesNumbers(next)) { setNotice(""); onChange(chart.id, { off: next }); } else setNotice("Cần giữ ít nhất một cột có số");
  };
  const ratioHidden = data.hidden.some((id) => off.includes(id));
  const mixedShown = data.series.some((item) => item.ratio && !off.includes(item.id)) && data.series.some((item) => !item.ratio && !off.includes(item.id));
  const move = (event, i) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    const target = event.key === "Home" ? 0 : event.key === "End" ? bars.length - 1 : step ? i + step : null;
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpenCell(bars[i].key, chart.id); return; }
    if (target == null || target < 0 || target >= bars.length) return;
    event.preventDefault();
    setAt(target);
    box.current?.querySelector(`[data-bar="${target}"]`)?.focus();
  };
  const enter = (key) => { setHover(key); onPeek(key); };
  const leave = () => { setHover(null); onPeek(null); };

  return <article id={`chart-${chart.id}`} tabIndex={-1} className="rd-card rd-chart">
    <div className="rd-chart-head">
      <div><span className="rd-kicker">Biểu đồ · trang {data.page}</span><h3>{data.title}</h3></div>
      <button type="button" className="rd-focus-close" onClick={() => onRemove(chart.id)} aria-label="Xóa biểu đồ">×</button>
    </div>
    {takeaway && <p className="rd-chart-take">{takeaway}</p>}
    {data.series.length > 1 && !data.turned && <div className="rd-chart-series" role="group" aria-label="Các cột trong biểu đồ">
      {data.series.map((item, i) => {
        const locked = !off.includes(item.id) && !leavesNumbers([...off, item.id]);
        return <button key={item.id} type="button" aria-pressed={!off.includes(item.id)} aria-disabled={locked || undefined} onClick={() => toggle(item.id)} style={{ "--part": partColor(i) }}><i aria-hidden="true" />{item.label}</button>;
      })}
    </div>}
    <p className="rd-chart-notice" role="status">{notice}</p>
    <div className="rd-chart-plot" ref={box}>
      <svg width={width} height={plan.height} role="group" aria-label={`Biểu đồ cột: ${data.title}. ${bars.length} cột. Mũi tên để đi qua từng cột, Enter để mở ô trên trang.`} onMouseLeave={leave}>
        <defs><pattern id={`hatch-${chart.id}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" className="rd-hatch-back" /><line x1="0" y1="0" x2="0" y2="6" className="rd-hatch-line" /></pattern></defs>
        <g aria-hidden="true">{plan.grid.map((line, i) => <g key={i}><line className={line.zero ? "rd-axis-zero" : "rd-axis-grid"} x1={line.x1} x2={line.x2} y1={line.y1} y2={line.y2} />{line.named !== false && <text className="rd-axis-text" x={line.lx} y={line.ly} textAnchor={line.anchor}>{line.label}</text>}</g>)}</g>
        <g aria-hidden="true">{plan.marks.filter((mark) => mark.groupLabel).map((mark) => <text key={mark.key} className="rd-chart-name" x={mark.x} y={mark.y} textAnchor={mark.anchor ?? "end"}><title>{mark.full}</title>{mark.text}</text>)}</g>
        {bars.map((bar, i) => {
          const active = bar.key === activeKey || bar.key === lit;
          return <g key={bar.key} data-bar={i} data-key={bar.key} className={`rd-bar${active ? " on" : ""}`} role="button" tabIndex={i === current ? 0 : -1} aria-label={spoken(bar)}
            onKeyDown={(event) => move(event, i)} onFocus={() => { setAt(i); enter(bar.key); }} onBlur={leave} onMouseEnter={() => enter(bar.key)} onClick={() => onOpenCell(bar.key, chart.id)}>
            <rect className="rd-bar-hit" x={bar.hit.x} y={bar.hit.y} width={bar.hit.w} height={bar.hit.h} />
            {bar.d && <path d={bar.d} fill={bar.color} />}
            {bar.d && bar.unsure && <path d={bar.d} fill={`url(#hatch-${chart.id})`} />}
            {bar.d && active && <path d={bar.d} className="rd-bar-ring" />}
            {!bar.label.hidden && <text className="rd-bar-value" x={bar.label.x} y={bar.label.y} textAnchor={bar.label.anchor} aria-hidden="true">{show(bar.value, share, data.percent)}{bar.unsure ? " ?" : ""}</text>}
            {bar.name && <text className="rd-chart-name" x={bar.name.x} y={bar.name.y} textAnchor={bar.name.anchor} aria-hidden="true"><title>{bar.group}</title>{bar.name.text}</text>}
          </g>;
        })}
      </svg>
    </div>
    <p className="rd-chart-tip" aria-hidden="true">{tip ? `${describe(tip)}: ${show(tip.value, share, data.percent)}${tip.unsure ? " · có thể sai" : ""} · trang ${data.page}` : ""}</p>
    {(unsure > 0 || data.notes.length > 0 || ratioHidden || mixedShown) && <ul className="rd-chart-notes">
      {ratioHidden && <li>Đã ẩn cột tỷ lệ (khác đơn vị)</li>}
      {mixedShown && <li><i className="rd-mark unsure" aria-hidden="true">?</i>Khác đơn vị, không so trực tiếp</li>}
      {unsure > 0 && <li><i className="rd-mark unsure" aria-hidden="true">?</i>Gạch chéo: có thể sai ({unsure})</li>}
      {data.notes.map((note) => <li key={note}>{note}</li>)}
    </ul>}
    <div className="rd-chart-actions">
      {data.share && <div className="rd-seg" role="group" aria-label="Cách vẽ">
        <button type="button" aria-pressed={!share} onClick={() => onChange(chart.id, { mode: "value" })}>Giá trị</button>
        <button type="button" aria-pressed={share} onClick={() => onChange(chart.id, { mode: "share" })}>Tỷ trọng</button>
      </div>}
      <button type="button" className="rd-link" onClick={() => onShowCells(chart.keys)}>Xem trên trang</button>
    </div>
    <details className="rd-chart-table">
      <summary>Xem bảng</summary>
      <table>
        <thead><tr><th scope="col">{data.turned ? "Kỳ" : "Dòng"}</th>{data.turned ? <th scope="col">{data.series[0].label}</th> : data.series.map((item) => <th key={item.id} scope="col">{item.label}</th>)}</tr></thead>
        <tbody>{data.groups.map((group) => <tr key={group.id}><th scope="row">{group.label}</th>
          {(data.turned ? data.series.slice(0, 1) : data.series).map((item) => { const bar = data.turned ? group.bars[0] : group.bars.find((entry) => entry.series === item.id); return <td key={item.id}>{bar ? `${show(barValue(bar, mode, data.share), share, data.percent)}${bar.unsure ? " (có thể sai)" : ""}` : "—"}</td>; })}</tr>)}</tbody>
      </table>
    </details>
  </article>;
}
