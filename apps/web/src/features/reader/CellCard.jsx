import { useEffect, useRef, useState } from "react";
import { answersUsingCell, cellName, cellNumber, cellUnsure, explainCell, sentenceAround } from "./cells.js";
import { EditForm } from "./DataPanel.jsx";
import { differsFromReading, formatNumber, scrollBehavior, valueWithUnit } from "./format.js";

/**
 * What one number on the page means, opened by tapping it: its value and
 * name, why it is that size, which answers and checks use it, and a way to fix
 * it or ask about it. A table cell's card opens below its row so the row name
 * and the column header stay visible; a number in running text shows the
 * sentence it was read from and opens below its line.
 */
export function CellCard({ cell, evidences, paragraph = null, notes, checks, basePath, narrow, onClose, onAsk, onGotoAnswer, onGotoCheck, onDismissCheck = null, onSaved, onConflict }) {
  const [editing, setEditing] = useState(false);
  const ref = useRef(null);
  useEffect(() => { setEditing(false); }, [cell.evidence_key]);
  useEffect(() => {
    // Move focus to the card itself: a screen reader reads it, Tab reaches its actions, Esc goes back to the cell.
    // On a phone the sheet is fixed to the page view, which places the cell itself.
    if (!narrow) ref.current?.scrollIntoView({ block: "nearest", behavior: scrollBehavior() });
    ref.current?.focus({ preventScroll: true });
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
  // A reading the app is not sure of still shows what the PDF prints, never a bare "—".
  const raw = String(cell.raw_text ?? "").trim();
  const shown = value != null ? valueWithUnit(cell) : raw && !/^[-–—.]+$/.test(raw) ? `«${raw}»` : "—";
  const spoken = value != null ? valueWithUnit(cell) : raw ? `chưa rõ, PDF ghi ${raw}` : "không có số";

  return <div ref={ref} tabIndex={-1} className={`rd-cellcard${narrow ? " sheet" : ""}`} role="dialog" aria-label={`${name}: ${spoken}`}>
    <div className="rd-cellcard-head">
      <div><b className={value == null && shown !== "—" ? "raw" : undefined}>{shown}</b><span>{name} · trang {cell.page_number}</span></div>
      <button type="button" className="rd-icon-button" onClick={onClose} aria-label="Đóng">×</button>
    </div>
    {edited && <p className="rd-cellcard-status">Đã sửa · gốc «{cell.raw_text || formatNumber(cell.original_numeric_value)}»</p>}
    {!edited && cellUnsure(cell) && <p className="rd-cellcard-status unsure"><i className="rd-mark unsure" aria-hidden="true">?</i>{value == null ? "Chưa rõ là số nào, xem trên trang rồi sửa nếu cần" : "Có thể đọc sai"}</p>}
    {editing
      ? <EditForm evidence={cell} all={evidences} basePath={basePath} onCancel={() => setEditing(false)} onConflict={onConflict} onSaved={(item, result) => { setEditing(false); onSaved(item, result); }} />
      : <>
        {sentence && <section><h4>Trong đoạn văn</h4><p className="rd-cellcard-quote">{sentence.before}<mark>{sentence.number}</mark>{sentence.after}</p></section>}
        {lines.length > 0 && <section><ul>{lines.map((line, index) => <li key={index} className={line.bad ? "bad" : line.unusual ? "unusual" : ""}>{line.bad && <i className="rd-mark bad" aria-hidden="true">!</i>}{line.unusual && !line.bad && <span>Đáng chú ý: </span>}{line.text}</li>)}</ul></section>}
        {(uses.length > 0 || problems.length > 0) && <section><h4>Có trong</h4><ul className="rd-uses">
          {uses.map((use) => <li key={use.id}><button type="button" className="rd-link" onClick={() => onGotoAnswer(use.id)}>{use.question || "Một câu trả lời"}</button></li>)}
          {problems.map((check) => <li key={check.chip.key} className="rd-use-problem"><button type="button" className="rd-link bad" onClick={() => onGotoCheck(check)}>Tổng {check.column} không khớp</button>{onDismissCheck && <button type="button" className="rd-button small" onClick={() => onDismissCheck(check)}>Bỏ qua</button>}</li>)}
        </ul></section>}
        <div className="rd-cellcard-actions">
          <button type="button" className="rd-button primary" onClick={() => onAsk(value == null ? `${name} là bao nhiêu?` : `${name} là ${formatNumber(cell.current_numeric_value)}, vì sao?`)}>Hỏi</button>
          {cell.current_revision_id && <button type="button" className="rd-button" onClick={() => setEditing(true)}>Sửa</button>}
        </div>
      </>}
  </div>;
}
