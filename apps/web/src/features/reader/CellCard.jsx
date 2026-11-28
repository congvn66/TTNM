import { useEffect, useRef, useState } from "react";
import { answersUsingCell, cellName, cellNumber, cellUnsure, explainCell, sentenceAround } from "./cells.js";
import { EditForm } from "./DataPanel.jsx";
import { differsFromReading, formatNumber, scrollBehavior, valueWithUnit } from "./format.js";

const TIP_KEY = "sourcelens-select-tip-v1";
const tipSeen = () => { try { return localStorage.getItem(TIP_KEY) === "yes"; } catch { return true; } };

/**
 * What one number on the page means, opened by tapping it: its value and
 * name, why it is that size, which answers and checks use it, and a way to fix
 * it or ask about it. A table cell's card opens below its row so the row name
 * and the column header stay visible; a number in running text shows the
 * sentence it was read from and opens below its line.
 */
export function CellCard({ cell, evidences, paragraph = null, notes, checks, basePath, narrow, onClose, onAsk, onGotoAnswer, onGotoCheck, onSaved, onConflict }) {
  const [editing, setEditing] = useState(false);
  const [tip] = useState(() => !tipSeen());
  const ref = useRef(null);
  useEffect(() => { setEditing(false); }, [cell.evidence_key]);
  useEffect(() => {
    // Move focus to the card itself: a screen reader reads it, Tab reaches its actions, Esc goes back to the cell.
    // On a phone the sheet is fixed to the page view, which places the cell itself.
    if (!narrow) ref.current?.scrollIntoView({ block: "nearest", behavior: scrollBehavior() });
    ref.current?.focus({ preventScroll: true });
    if (tip) { try { localStorage.setItem(TIP_KEY, "yes"); } catch { /* private mode */ } }
  }, [cell.evidence_key]);

  const value = cellNumber(cell);
  const name = cellName(cell);
  const edited = differsFromReading(cell.current_numeric_value, cell.original_numeric_value);
  const lines = explainCell(cell, evidences);
  const uses = answersUsingCell(cell.evidence_key, notes);
  const problems = (checks ?? []).filter((check) => !check.ok && check.keys?.includes(cell.evidence_key));
  const inTable = Boolean(cell.table_locator);
  const where = cell.paragraph_locator;
  const sentence = !inTable && where && paragraph ? sentenceAround(paragraph.text, where.start, where.end) : null;

  return <div ref={ref} tabIndex={-1} className={`rd-cellcard${narrow ? " sheet" : ""}`} role="dialog" aria-label={`${name}: ${value == null ? "không có số" : valueWithUnit(cell)}`}>
    <div className="rd-cellcard-head">
      <div><b>{value == null ? "—" : valueWithUnit(cell)}</b><span>{name} · trang {cell.page_number}</span></div>
      <button type="button" className="rd-icon-button" onClick={onClose} aria-label="Đóng (Esc)">×</button>
    </div>
    {edited && <p className="rd-cellcard-status">Đã sửa · PDF ghi «{cell.raw_text || formatNumber(cell.original_numeric_value)}»</p>}
    {!edited && cellUnsure(cell) && <p className="rd-cellcard-status unsure"><i className="rd-mark unsure" aria-hidden="true">?</i>Mình chưa chắc đọc đúng số này, bạn so với trang giúp nhé.</p>}
    {editing
      ? <EditForm evidence={cell} all={evidences} basePath={basePath} onCancel={() => setEditing(false)} onConflict={onConflict} onSaved={(item, result) => { setEditing(false); onSaved(item, result); }} />
      : <>
        {sentence && <section><h4>Trong đoạn văn</h4><p className="rd-cellcard-quote">{sentence.before}<mark>{sentence.number}</mark>{sentence.after}</p></section>}
        {lines.length > 0 && <section><h4>Vì sao số này như vậy</h4><ul>{lines.map((line, index) => <li key={index} className={line.bad ? "bad" : line.unusual ? "unusual" : ""}>{line.bad && <i className="rd-mark bad" aria-hidden="true">!</i>}{line.unusual && !line.bad && <span>Đáng chú ý: </span>}{line.text}</li>)}</ul></section>}
        {(uses.length > 0 || problems.length > 0) && <section><h4>Dùng ở đâu</h4><ul className="rd-uses">
          {uses.map((use) => <li key={use.id}><button type="button" className="rd-link" onClick={() => onGotoAnswer(use.id)}>{use.question || "Một câu trả lời"}</button></li>)}
          {problems.map((check) => <li key={check.chip.key}><button type="button" className="rd-link bad" onClick={() => onGotoCheck(check)}>Dòng tổng {check.column} không khớp, xem chỗ lệch</button></li>)}
        </ul></section>}
        <div className="rd-cellcard-actions">
          <button type="button" className="rd-button primary" onClick={() => onAsk(value == null ? `${name} là bao nhiêu?` : `${name} là ${formatNumber(cell.current_numeric_value)}, vì sao?`)}>{inTable ? "Hỏi về ô này" : "Hỏi về số này"}</button>
          {cell.current_revision_id && <button type="button" className="rd-button" onClick={() => setEditing(true)}>Sửa số đọc sai</button>}
        </div>
        {tip && inTable && <p className="rd-tip">{narrow ? "Mẹo: bật «Chọn vùng» rồi kéo qua nhiều ô để cộng nhanh." : "Mẹo: kéo qua nhiều ô, hoặc giữ Shift rồi bấm ô khác, để cộng nhanh."}</p>}
      </>}
  </div>;
}
