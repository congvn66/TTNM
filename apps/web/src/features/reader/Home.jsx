import { useRef, useState } from "react";

export const SAMPLE_URL = "/samples/bao-cao-mau-huong-lua.pdf";

// A ready report has no status text: its green dot says it.
function statusText(report) {
  return ({ queued: "Đang chờ", processing: "Đang đọc", ready: "", failed: "Không đọc được" }[report.extraction_status] ?? "Đang đọc");
}

/** "3 trang · Đang đọc · hôm nay 10:00", leaving out the parts a report does not have. */
export function reportMeta(report, { withDate = true } = {}) {
  return [report.page_count ? `${report.page_count} trang` : "", statusText(report), withDate ? when(report.created_at) : ""].filter(Boolean).join(" · ");
}

export function StatusDot({ report }) {
  return <span className={`rd-dot ${report.extraction_status}`} aria-hidden="true" />;
}

function when(value) {
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
  const touch = typeof window !== "undefined" && Boolean(window.matchMedia?.("(pointer: coarse)").matches);
  return <div className={`rd-drop${over ? " over" : ""}${compact ? " compact" : ""}`}
    onDragOver={(event) => { event.preventDefault(); setOver(true); }}
    onDragLeave={() => setOver(false)}
    onDrop={(event) => { event.preventDefault(); setOver(false); onFile(event.dataTransfer.files?.[0]); }}>
    {uploading
      ? <div className="rd-drop-busy" role="status"><span className="rd-spinner large" aria-hidden="true" /><b>Đang tải lên {uploading.name}…</b></div>
      : <>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M12 17v-6M9.5 13.5 12 11l2.5 2.5" /></svg>
        {/* A finger cannot drag a file: on touch the box only offers to pick one. */}
        <b>{touch ? "Chọn tệp PDF" : "Kéo tệp PDF vào đây"}</b>
        <button type="button" className="rd-button primary" onClick={() => inputRef.current?.click()}>Chọn tệp</button>
        <small>PDF, tối đa 100 MB</small>
      </>}
    <input ref={inputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => { onFile(event.target.files?.[0]); event.target.value = ""; }} />
  </div>;
}

export function Home({ onFile, onSample, uploading, project = "" }) {
  return <main className="rd-home" id="main-content">
    <section className="rd-hero">
      <h1 className="rd-sr">Báo cáo</h1>
      <DropZone onFile={onFile} uploading={uploading} />
      {project && <p className="rd-small">Lưu vào {project}</p>}
      <button type="button" className="rd-sample" onClick={onSample} disabled={Boolean(uploading)}>Mở báo cáo mẫu</button>
    </section>
  </main>;
}
