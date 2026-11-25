import "./toolAnswer.css";

// PDF text and the stored value differ when a person corrected the number.
function differsFromPdf(raw, value) {
  if (raw == null || value == null) return false;
  const number = Number(String(raw).replace(/[^\d.-]/g, ""));
  return !Number.isFinite(number) || number !== Number(value);
}

export function EvidenceList({ items, onCitation }) {
  return <section className="answer-section evidence-list" aria-label="Bằng chứng trong PDF">
    <h4>Bằng chứng trong PDF</h4>
    {items.map((item, index) => {
      const unverified = item.kind === "data" && item.data_status && item.data_status !== "valid";
      const kindLabel = item.kind === "text" ? "trích nguyên văn" : item.kind === "data" ? item.method_label : "trang đã đọc";
      return <button type="button" className={`evidence-item ${item.kind}${unverified ? " unverified" : ""}`} key={`${item.kind}-${item.evidence_key ?? item.quote ?? item.page}-${index}`} onClick={() => onCitation?.(item.page, item.quote ?? "", item.bbox)} title="Mở vị trí trong PDF">
        <span className="evidence-index">{index + 1}</span>
        <span className="evidence-body">
          <span className="evidence-meta">Trang {item.page} · {kindLabel}</span>
          {item.kind === "text" && <q>{item.quote}</q>}
          {item.kind === "data" && <span className="evidence-data"><span>{item.label}</span><b>{item.value ?? item.raw_text ?? "—"}</b></span>}
          {item.kind === "data" && differsFromPdf(item.raw_text, item.value) && <small>Chữ trong PDF: “{item.raw_text}”{item.value ? " · đã sửa trong Dữ liệu" : ""}</small>}
          {unverified && <small className="evidence-warning">Chưa xác minh, kiểm tra trong Dữ liệu</small>}
        </span>
      </button>;
    })}
  </section>;
}

export function ScriptCard({ formula, onCitation }) {
  return <div className="formula-card script-card">
    <div className="script-head"><strong>Script Python</strong><em className="formula-verified">✓ đã chạy</em></div>
    {formula.substitution && <span>{formula.substitution}</span>}
    {formula.inputs?.length > 0 && <div className="script-inputs" aria-label="Dữ liệu đầu vào của script">
      <div className="script-input head"><span>Dữ liệu đầu vào</span><span>Giá trị</span><span>Trang</span></div>
      {formula.inputs.map((input) => <button type="button" className="script-input" key={input.evidence_key} title={input.evidence_key} onClick={() => onCitation?.(input.page, "", input.bbox)}><span>{input.label}</span><b>{input.value}</b><span>p.{input.page}</span></button>)}
    </div>}
    {formula.manual_numbers?.length > 0 && <small className="script-manual">Số nhập tay trong code, không lấy từ bảng Dữ liệu: {formula.manual_numbers.join(", ")}</small>}
    <details><summary>Code</summary><pre>{formula.expression}</pre></details>
    {formula.stdout && <pre className="script-stdout">{formula.stdout}</pre>}
    <b>Kết quả: {formula.result}</b>
  </div>;
}
