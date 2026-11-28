import { useEffect, useMemo, useState } from "react";
import { request } from "../../shared/api/client.js";

const SESSION_KEY = "sourcelens-active-session";
const DOCUMENT_KEY = "sourcelens-active-document";
const statusLabel = {
  queued: "Đang chuẩn bị",
  processing: "Đang đọc tài liệu",
  completed: "Sẵn sàng để hỏi",
  ready: "Sẵn sàng để hỏi",
  failed: "Không thể đọc — thử lại",
};
const formatBytes = (value = 0) => value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`;

function ErrorNotice({ children, onRetry }) {
  return <div className="library-notice error" role="alert"><strong>Không thể hoàn tất thao tác</strong><span>{children}</span>{onRetry && <button type="button" onClick={onRetry}>Thử lại</button>}</div>;
}

function LibraryDialog({ dialog, busy, onClose, onConfirm }) {
  const [value, setValue] = useState(dialog?.value ?? "");
  useEffect(() => setValue(dialog?.value ?? ""), [dialog]);
  if (!dialog) return null;
  const naming = dialog.kind === "name";
  return <div className="resource-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="resource-modal" role="dialog" aria-modal="true" aria-labelledby="library-dialog-title">
      <div className={`resource-modal-icon ${dialog.danger ? "danger" : ""}`}><span aria-hidden="true">{dialog.danger ? "!" : "✎"}</span></div>
      <div><p className="dialog-kicker">{dialog.danger ? "XÁC NHẬN" : "CHỈNH SỬA"}</p><h2 id="library-dialog-title">{dialog.title}</h2><p>{dialog.description}</p></div>
      {naming && <label className="dialog-input-label">Tên hiển thị<input autoFocus value={value} maxLength={120} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); onConfirm(value.trim()); } }} /></label>}
      <div className="resource-modal-actions"><button type="button" className="dialog-secondary" onClick={onClose} disabled={busy}>Hủy</button><button type="button" className={dialog.danger ? "dialog-danger" : "dialog-primary"} disabled={busy || (naming && !value.trim())} onClick={() => onConfirm(value.trim())}>{busy ? "Đang lưu…" : dialog.danger ? "Xác nhận" : "Lưu thay đổi"}</button></div>
    </section>
  </div>;
}

export default function LibraryScreen({ onNavigate }) {
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [library, setLibrary] = useState(null);
  const [query, setQuery] = useState("");
  const [folderId, setFolderId] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState(null);

  async function loadProjects(preferred = projectId) {
    const body = await request("/api/v1/projects");
    const next = body.projects ?? [];
    setProjects(next);
    const selected = next.find((item) => item.id === preferred)?.id ?? next[0]?.id ?? null;
    setProjectId(selected);
    return selected;
  }

  async function loadLibrary(id = projectId) {
    if (!id) { setLibrary(null); return; }
    setLibrary(await request(`/api/v1/projects/${id}/library`));
  }

  useEffect(() => {
    let disposed = false;
    (async () => {
      try { await loadProjects(); }
      catch (reason) { if (!disposed) setError(reason.message); }
      finally { if (!disposed) setLoading(false); }
    })();
    return () => { disposed = true; };
  }, []);

  useEffect(() => { if (projectId) loadLibrary(projectId).catch((reason) => setError(reason.message)); }, [projectId]);

  const folders = library?.folders ?? [];
  const documents = useMemo(() => (library?.documents ?? []).filter((document) => {
    const text = `${document.display_name || document.file_name || document.title} ${document.session_title || ""}`.toLowerCase();
    return text.includes(query.trim().toLowerCase()) && (folderId === "all" || (folderId === "unfiled" ? !document.folder_id : document.folder_id === folderId));
  }), [library?.documents, query, folderId]);

  async function mutate(action, { selectedProjectId } = {}) {
    setBusy(true); setError("");
    try {
      const result = await action();
      const preferred = selectedProjectId || result?.project?.id || projectId;
      const selected = await loadProjects(preferred);
      if (selected) await loadLibrary(selected);
    }
    catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  }

  function openDocument(document) {
    if (!document.session_id) return;
    localStorage.setItem(SESSION_KEY, document.session_id);
    localStorage.setItem(DOCUMENT_KEY, document.document_id);
    onNavigate?.("/app/workspace");
  }

  function openNameDialog(title, value, description, action) { setDialog({ kind: "name", title, value, description, action }); }
  function openConfirmDialog(title, description, action) { setDialog({ kind: "confirm", title, description, danger: true, action }); }
  async function confirmDialog(value) { const action = dialog?.action; setDialog(null); if (action) await action(value); }
  function createProject() { openNameDialog("Tạo dự án mới", "Dự án mới", "Dự án gom các báo cáo và thư mục của cùng một việc.", (value) => mutate(async () => { const body = await request("/api/v1/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value }) }); setProjectId(body.project.id); })); }
  function createFolder() { if (!projectId) return; openNameDialog("Tạo thư mục", "Thư mục mới", "Đặt tên để dễ tìm báo cáo trong dự án này.", (value) => mutate(() => request(`/api/v1/projects/${projectId}/folders`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value }) }))); }
  function renameProject() { const project = projects.find((item) => item.id === projectId); if (project) openNameDialog("Đổi tên dự án", project.name, "Tên mới chỉ thay đổi cách hiển thị trong thư viện.", (value) => mutate(() => request(`/api/v1/projects/${projectId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value }) }))); }
  function renameFolder(folder) { openNameDialog("Đổi tên thư mục", folder.name, "Tài liệu bên trong thư mục không bị thay đổi.", (value) => mutate(() => request(`/api/v1/folders/${folder.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value, expected_version: folder.version }) }))); }

  return <div className="library-shell library-app">
    <header className="library-topbar"><div className="library-brand"><span>S</span><strong>SourceLens</strong></div><nav aria-label="Điều hướng chính"><button type="button" onClick={() => onNavigate?.("/app/workspace")}>Báo cáo</button><button type="button" className="active">Thư viện</button></nav><span className="library-topbar-spacer" /><button type="button" className="library-secondary" onClick={() => onNavigate?.("/app/settings/profile")}>Tài khoản</button></header>
    <main className="library-main" id="library-content">
      <header className="library-header"><div><h1>Thư viện tài liệu</h1><p className="library-subtitle">Xếp báo cáo theo dự án và thư mục.</p></div><div className="library-header-actions"><button type="button" className="library-secondary" onClick={() => onNavigate?.("/app/workspace?upload=1")}>Tải lên báo cáo</button><button type="button" className="library-primary" disabled={busy} onClick={createProject}>Tạo dự án</button></div></header>
      {error && <ErrorNotice onRetry={() => { setError(""); loadProjects(projectId).then((id) => loadLibrary(id)).catch((reason) => setError(reason.message)); }}>{error}</ErrorNotice>}
      {loading ? <div className="library-state" role="status"><span className="loading-dot" /> Đang tải thư viện…</div> : <div className="library-workspace">
        <aside className="library-rail" aria-label="Dự án và thư mục"><div className="library-rail-title"><span>Dự án</span><button type="button" aria-label="Tạo dự án" onClick={createProject}>＋</button></div><div className="library-project-list">{projects.map((project) => <button type="button" key={project.id} className={project.id === projectId ? "selected" : ""} onClick={() => { setProjectId(project.id); setFolderId("all"); }}><strong>{project.name}</strong><small>{project.session_count} phiên · {project.document_count} tài liệu</small></button>)}</div>{library && <><div className="library-rail-title folder-title"><span>Thư mục</span><button type="button" aria-label="Tạo thư mục" onClick={createFolder}>＋</button></div><div className="library-folder-list"><button type="button" className={folderId === "all" ? "selected" : ""} onClick={() => setFolderId("all")}>Tất cả tài liệu</button><button type="button" className={folderId === "unfiled" ? "selected" : ""} onClick={() => setFolderId("unfiled")}>Chưa phân loại</button>{folders.map((folder) => <div className="library-folder-row" key={folder.id}><button type="button" className={folderId === folder.id ? "selected" : ""} onClick={() => setFolderId(folder.id)}>{folder.name}</button><span><button type="button" aria-label={`Đổi tên ${folder.name}`} onClick={() => renameFolder(folder)}>⋯</button><button type="button" aria-label={`Xóa ${folder.name}`} onClick={() => openConfirmDialog(`Xóa thư mục “${folder.name}”?`, "Tài liệu sẽ chuyển về trạng thái chưa phân loại.", () => mutate(() => request(`/api/v1/folders/${folder.id}`, { method: "DELETE" })))}>×</button></span></div>)}</div></>}</aside>
        <section className="library-content"><div className="library-project-heading"><div><h2>{projects.find((item) => item.id === projectId)?.name || "Thư viện"}</h2><p>{library?.sessions?.length ?? 0} phiên làm việc · {library?.documents?.length ?? 0} tài liệu</p></div><div className="library-inline-actions"><button type="button" className="library-secondary" onClick={renameProject}>Đổi tên</button><button type="button" className="library-secondary" onClick={() => openConfirmDialog("Lưu trữ dự án này?", "Dự án phải không còn báo cáo đang mở. Dữ liệu cũ vẫn được giữ.", () => mutate(() => request(`/api/v1/projects/${projectId}`, { method: "DELETE" })))}>Lưu trữ</button></div></div><div className="library-toolbar"><input aria-label="Tìm tài liệu" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm báo cáo…" /><span>{documents.length} kết quả</span></div>{!documents.length ? <div className="library-state"><strong>{library?.documents?.length ? "Không có tài liệu phù hợp" : "Dự án chưa có báo cáo"}</strong><span>Tải lên một báo cáo PDF hoặc chọn thư mục khác.</span><button type="button" onClick={() => onNavigate?.("/app/workspace?upload=1")}>Tải lên báo cáo</button></div> : <div className="library-grid">{documents.map((document) => <article className="library-card" key={document.document_id}><div className="library-card-top"><span className="library-file-icon">PDF</span><span className={`status-chip ${document.extraction_status}`}>{statusLabel[document.extraction_status] || "Chưa xử lý"}</span></div><h2 title={document.display_name || document.file_name}>{document.display_name || document.file_name}</h2><p className="library-session">{document.session_title || "Chưa gắn phiên"}</p><p className="library-meta">{formatBytes(document.byte_size)} · {document.page_count ?? "?"} trang</p><label className="library-folder-select">Thư mục<select value={document.folder_id || ""} disabled={busy} onChange={(event) => mutate(() => request(`/api/v1/projects/${projectId}/documents/${document.document_id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder_id: event.target.value || null, expected_version: document.version }) }))}><option value="">Chưa phân loại</option>{folders.map((folder) => <option value={folder.id} key={folder.id}>{folder.name}</option>)}</select></label><button type="button" className="library-open" onClick={() => openDocument(document)}>Mở báo cáo <span aria-hidden="true">→</span></button></article>)}</div>}</section>
      </div>}
    </main>
    <LibraryDialog dialog={dialog} busy={busy} onClose={() => setDialog(null)} onConfirm={confirmDialog} />
  </div>;
}
