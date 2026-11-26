import "./toolAnswer.css";
import { dataStatusLabel, formatNumber, numbersDiffer, readableLabel, resultRows } from "./format.js";

// A number counts as edited when the value the answer used is not the value
// first read from the PDF. Both are canonical decimals from the API; the PDF
// text ("21.350") is never compared, it only shows what the page says.
function editedRow(item, evidenceByKey) {
  const row = evidenceByKey?.get(item.evidence_key);
  return row && numbersDiffer(item.value, row.original_numeric_value) ? row : null;
}

function itemLabel(item) {
  return readableLabel(item.label) || `Số ở trang ${item.page}`;
}

export function EvidenceList({ items, evidenceByKey, onCitation }) {
  return <section className="answer-section evidence-list" aria-label="Bằng chứng trong PDF">
    <h4>Bằng chứng trong PDF</h4>
    {items.map((item, index) => {
      const status = item.kind === "data" ? dataStatusLabel(item.data_status) : "";
      const kindLabel = item.kind === "text" ? "trích nguyên văn" : item.kind === "data" ? item.method_label : "trang đã đọc";
      const edited = item.kind === "data" ? editedRow(item, evidenceByKey) : null;
      return <button type="button" className={`evidence-item ${item.kind}${status ? " unverified" : ""}`} key={`${item.kind}-${item.evidence_key ?? item.quote ?? item.page}-${index}`} onClick={() => onCitation?.(item.page, item.quote ?? "", item.bbox)} title="Mở vị trí trong PDF">
        <span className="evidence-index">{index + 1}</span>
        <span className="evidence-body">
          <span className="evidence-meta">Trang {item.page} · {kindLabel}</span>
          {item.kind === "text" && <q>{item.quote}</q>}
          {item.kind === "data" && <span className="evidence-data"><span>{itemLabel(item)}</span><b>{formatNumber(item.value) || item.raw_text || "—"}</b></span>}
          {edited && <small>Đã sửa trong Dữ liệu · số trong PDF: “{item.raw_text ?? formatNumber(edited.original_numeric_value)}”</small>}
          {status && <small className="evidence-warning">{status} · kiểm tra trong Dữ liệu</small>}
        </span>
      </button>;
    })}
  </section>;
}

function ScriptResult({ result }) {
  const rows = resultRows(result);
  if (rows.length === 1 && !rows[0].name) return <b>Kết quả: {rows[0].value}</b>;
  return <div className="script-result"><b>Kết quả</b><dl>{rows.map((row) => <div key={row.name}><dt>{row.name}</dt><dd>{row.value}</dd></div>)}</dl></div>;
}

export function ScriptCard({ formula, onCitation }) {
  const inputs = formula.inputs ?? [];
  return <div className="formula-card script-card">
    <div className="script-head"><strong>Phép tính</strong><em className="formula-verified">✓ đã chạy</em></div>
    {formula.substitution && <span>{formula.substitution}</span>}
    {inputs.length > 0 && <div className="script-inputs" aria-label="Số liệu dùng để tính">
      <div className="script-input head" aria-hidden="true"><span>Số liệu dùng để tính</span><span>Giá trị</span><span>Trang</span></div>
      {inputs.map((input) => <button type="button" className="script-input" key={input.evidence_key} onClick={() => onCitation?.(input.page, "", input.bbox)} aria-label={`${itemLabel(input)}: ${formatNumber(input.value)}, trang ${input.page}. Mở vị trí trong PDF`}><span>{itemLabel(input)}</span><b>{formatNumber(input.value)}</b><span>{input.page}</span></button>)}
    </div>}
    {formula.manual_numbers?.length > 0 && <small className="script-manual">Số nhập tay trong code, không lấy từ bảng Dữ liệu: {formula.manual_numbers.map(formatNumber).join(", ")}</small>}
    <details><summary>Xem code Python</summary><pre>{formula.expression}</pre>
      {inputs.length > 0 && <dl className="script-keys" aria-label="Các số trong code">{inputs.map((input) => <div key={input.evidence_key}><dt><code>{input.evidence_key}</code></dt><dd>{itemLabel(input)} · {formatNumber(input.value)}</dd></div>)}</dl>}
    </details>
    {formula.stdout && <pre className="script-stdout">{formula.stdout}</pre>}
    <ScriptResult result={formula.result} />
  </div>;
}
