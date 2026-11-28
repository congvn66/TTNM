import { useRef, useState } from "react";

export const SAMPLE_URL = "/samples/bao-cao-mau-huong-lua.pdf";

function statusText(report) {
  return ({ queued: "Đang chờ đọc", processing: "Đang đọc", ready: "Sẵn sàng", failed: "Chưa đọc được" }[report.extraction_status] ?? "Đang kiểm tra");
}

export function StatusDot({ report }) {
  return <span className={`rd-dot ${report.extraction_status}`} aria-hidden="true" />;
}

export function when(value) {
  const time = Date.parse(value ?? "");
  if (!Number.isFinite(time)) return "";
  const date = new Date(time);
  const today = new Date().toDateString() === date.toDateString();
  const clock = date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  return today ? `hôm nay ${clock}` : `${date.toLocaleDateString("vi-VN", { day: "numeric", month: "numeric" })} ${clock}`;
}

export function DropZone({ onFile, uploading, compact = false }) {
  const inputRef = useRef(null);
  const [over, setOver] = useState(false);
  return <div className={`rd-drop${over ? " over" : ""}${compact ? " compact" : ""}`}
    onDragOver={(event) => { event.preventDefault(); setOver(true); }}
    onDragLeave={() => setOver(false)}
    onDrop={(event) => { event.preventDefault(); setOver(false); onFile(event.dataTransfer.files?.[0]); }}>
    {uploading
      ? <div className="rd-drop-busy" role="status"><span className="rd-spinner large" aria-hidden="true" /><b>Đang tải lên {uploading.name}…</b></div>
      : <>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M12 17v-6M9.5 13.5 12 11l2.5 2.5" /></svg>
        <b>Thả báo cáo PDF vào đây</b>
        <button type="button" className="rd-button primary" onClick={() => inputRef.current?.click()}>Chọn tệp PDF</button>
        <small>Báo cáo có bảng số liệu, tối đa 100 MB</small>
      </>}
    <input ref={inputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => { onFile(event.target.files?.[0]); event.target.value = ""; }} />
  </div>;
}

export function Home({ reports, onOpen, onFile, onSample, uploading, onDelete }) {
  const [showAll, setShowAll] = useState(false);
  return <main className="rd-home" id="main-content">
    <section className="rd-hero">
      <h1>Hỏi báo cáo, thấy ngay mỗi con số nằm ở đâu</h1>
      <p>Tải lên một báo cáo PDF. SourceLens đọc từng con số, tự kiểm tra các dòng tổng, rồi trả lời câu hỏi của bạn và chỉ đúng ô số trên trang.</p>
      <DropZone onFile={onFile} uploading={uploading} />
      <button type="button" className="rd-sample" onClick={onSample} disabled={Boolean(uploading)}>Chưa có báo cáo? <b>Dùng thử báo cáo mẫu</b></button>
    </section>
    {reports.length > 0 && <section className="rd-recent" aria-label="Báo cáo gần đây">
      <h2>Báo cáo của bạn</h2>
      <ul>{(showAll ? reports : reports.slice(0, 5)).map((report) => <li key={report.id}>
        <button type="button" className="rd-recent-open" onClick={() => onOpen(report.id)}>
          <StatusDot report={report} />
          <span><b>{report.file_name}</b><small>{report.page_count ? `${report.page_count} trang · ` : ""}{statusText(report)}{when(report.created_at) ? ` · ${when(report.created_at)}` : ""}</small></span>
        </button>
        <button type="button" className="rd-icon" aria-label={`Xoá ${report.file_name}`} title="Xoá báo cáo" onClick={() => onDelete(report)}>×</button>
      </li>)}</ul>
      {reports.length > 5 && <button type="button" className="rd-link rd-more" onClick={() => setShowAll((value) => !value)}>{showAll ? "Thu gọn" : `Xem cả ${reports.length} báo cáo`}</button>}
    </section>}
    <ol className="rd-how" aria-label="Cách dùng">
      <li><span>1</span><div><b>Tải lên báo cáo</b><p>Đợi khoảng nửa phút. Xong sẽ có tiếng chuông.</p></div></li>
      <li><span>2</span><div><b>Hỏi bằng tiếng Việt</b><p>Ví dụ: “Doanh thu quý 2 tăng bao nhiêu?”</p></div></li>
      <li><span>3</span><div><b>Chạm vào số màu xanh</b><p>Ô số gốc trên trang sẽ sáng lên để bạn tự kiểm.</p></div></li>
    </ol>
  </main>;
}

export { statusText };
