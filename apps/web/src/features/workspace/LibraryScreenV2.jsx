import { useEffect, useMemo, useState } from "react";
import { request } from "../../shared/api/client.js";

const SESSION_KEY = "sourcelens-active-session";
const DOCUMENT_KEY = "sourcelens-active-document";
// A ready report shows no chip.
const statusLabel = { queued: "Đang chờ", processing: "Đang đọc", failed: "Không đọc được" };
const formatBytes = (value = 0) => value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toLocaleString("vi-VN", { maximumFractionDigits: 1 })} MB`;
// Resets the browser button look so the title keeps the card's h2 style.
const TITLE_BUTTON_STYLE = { display: "block", width: "100%", padding: 0, border: 0, background: "none", color: "inherit", font: "inherit", textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", cursor: "pointer" };

function ErrorNotice({ children, onRetry }) {
  return <div className="library-notice error" role="alert"><span>{children}</span>{onRetry && <button type="button" onClick={onRetry}>Thử lại</button>}</div>;
}

function LibraryDialog({ dialog, busy, onClose, onConfirm }) {
  const [value, setValue] = useState(dialog?.value ?? "");
  useEffect(() => setValue(dialog?.value ?? ""), [dialog]);
  if (!dialog) return null;
  const naming = dialog.kind === "name";
  return <div className="resource-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="resource-modal" role="dialog" aria-modal="true" aria-labelledby="library-dialog-title">
      <div className={`resource-modal-icon ${dialog.danger ? "danger" : ""}`}><span aria-hidden="true">{dialog.danger ? "!" : "✎"}</span></div>
      <div><h2 id="library-dialog-title">{dialog.title}</h2>{dialog.description && <p>{dialog.description}</p>}</div>
      {naming && <label className="dialog-input-label">Tên<input autoFocus value={value} maxLength={120} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); onConfirm(value.trim()); } }} /></label>}
      <div className="resource-modal-actions"><button type="button" className="dialog-secondary" onClick={onClose} disabled={busy}>Hủy</button><button type="button" className={dialog.danger ? "dialog-danger" : "dialog-primary"} disabled={busy || (naming && !value.trim())} onClick={() => onConfirm(value.trim())}>{busy ? "Đang lưu…" : dialog.confirmLabel}</button></div>
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
    const text = `${document.display_name || document.file_name || document.title}`.toLowerCase();
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

  function openNameDialog(title, value, confirmLabel, action) { setDialog({ kind: "name", title, value, confirmLabel, action }); }
  function openConfirmDialog(title, description, action) { setDialog({ kind: "confirm", title, description, danger: true, confirmLabel: "Xóa", action }); }
  async function confirmDialog(value) { const action = dialog?.action; setDialog(null); if (action) await action(value); }
  function createProject() { openNameDialog("Tạo dự án", "Dự án mới", "Tạo", (value) => mutate(async () => { const body = await request("/api/v1/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value }) }); setProjectId(body.project.id); })); }
  function createFolder() { if (!projectId) return; openNameDialog("Tạo thư mục", "Thư mục mới", "Tạo", (value) => mutate(() => request(`/api/v1/projects/${projectId}/folders`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value }) }))); }
  function renameProject() { const project = projects.find((item) => item.id === projectId); if (project) openNameDialog("Đổi tên dự án", project.name, "Lưu", (value) => mutate(() => request(`/api/v1/projects/${projectId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value }) }))); }
  function renameFolder(folder) { openNameDialog("Đổi tên thư mục", folder.name, "Lưu", (value) => mutate(() => request(`/api/v1/folders/${folder.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: value, expected_version: folder.version }) }))); }

  return <div className="library-shell library-app">
    <header className="library-topbar"><div className="library-brand"><span>S</span><strong>SourceLens</strong></div><nav aria-label="Điều hướng chính"><button type="button" onClick={() => onNavigate?.("/app/workspace")}>Báo cáo</button><button type="button" className="active">Thư viện</button></nav><span className="library-topbar-spacer" /><button type="button" className="library-secondary" onClick={() => onNavigate?.("/app/settings/profile")}>Cài đặt</button></header>
    <main className="library-main" id="library-content">
      <header className="library-header"><div><h1>Thư viện</h1></div><div className="library-header-actions"><button type="button" className="library-secondary" onClick={() => onNavigate?.("/app/workspace?upload=1")}>Tải lên</button><button type="button" className="library-primary" disabled={busy} onClick={createProject}>Tạo dự án</button></div></header>
      {error && <ErrorNotice onRetry={() => { setError(""); loadProjects(projectId).then((id) => loadLibrary(id)).catch((reason) => setError(reason.message)); }}>{error}</ErrorNotice>}
      {loading ? <div className="library-state" role="status"><span className="loading-dot" /> Đang tải thư viện…</div> : <div className="library-workspace">
        <aside className="library-rail" aria-label="Dự án và thư mục"><div className="library-rail-title"><span>Dự án</span><button type="button" aria-label="Tạo dự án" onClick={createProject}>+</button></div><div className="library-project-list">{projects.map((project) => <button type="button" key={project.id} className={project.id === projectId ? "selected" : ""} onClick={() => { setProjectId(project.id); setFolderId("all"); }}><strong>{project.name}</strong><small>{project.document_count} báo cáo</small></button>)}</div>{library && <><div className="library-rail-title folder-title"><span>Thư mục</span><button type="button" aria-label="Tạo thư mục" onClick={createFolder}>+</button></div><div className="library-folder-list"><button type="button" className={folderId === "all" ? "selected" : ""} onClick={() => setFolderId("all")}>Tất cả</button><button type="button" className={folderId === "unfiled" ? "selected" : ""} onClick={() => setFolderId("unfiled")}>Chưa phân loại</button>{folders.map((folder) => <div className="library-folder-row" key={folder.id}><button type="button" className={folderId === folder.id ? "selected" : ""} onClick={() => setFolderId(folder.id)}>{folder.name}</button><span><button type="button" aria-label={`Đổi tên ${folder.name}`} onClick={() => renameFolder(folder)}><span aria-hidden="true">✎</span></button><button type="button" aria-label={`Xóa ${folder.name}`} onClick={() => openConfirmDialog(`Xóa thư mục “${folder.name}”?`, "Báo cáo trong thư mục sẽ chuyển về Chưa phân loại.", () => mutate(() => request(`/api/v1/folders/${folder.id}`, { method: "DELETE" })))}>×</button></span></div>)}</div></>}</aside>
        <section className="library-content"><div className="library-project-heading"><div><h2>{projects.find((item) => item.id === projectId)?.name || "Thư viện"}</h2><p>{library?.documents?.length ?? 0} báo cáo</p></div><div className="library-inline-actions"><button type="button" className="library-secondary" onClick={renameProject}>Đổi tên</button><button type="button" className="library-secondary" onClick={() => openConfirmDialog("Xóa dự án này?", "", () => mutate(() => request(`/api/v1/projects/${projectId}`, { method: "DELETE" })))}>Xóa dự án</button></div></div><div className="library-toolbar"><input aria-label="Tìm báo cáo" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm báo cáo" /><span>{documents.length} kết quả</span></div>{!documents.length ? (library?.documents?.length ? <div className="library-state"><strong>Không có kết quả</strong></div> : <div className="library-state"><strong>Chưa có báo cáo</strong><button type="button" onClick={() => onNavigate?.("/app/workspace?upload=1")}>Tải lên</button></div>) : <div className="library-grid">{documents.map((document) => <article className="library-card" key={document.document_id} style={{ cursor: "pointer" }} onClick={(event) => { if (!event.target.closest("label, select")) openDocument(document); }}>{statusLabel[document.extraction_status] && <div className="library-card-top"><span className={`status-chip ${document.extraction_status}`}>{statusLabel[document.extraction_status]}</span></div>}<h2><button type="button" style={TITLE_BUTTON_STYLE} title={document.display_name || document.file_name}>{document.display_name || document.file_name}</button></h2><p className="library-meta">{formatBytes(document.byte_size)} · {document.page_count ?? "?"} trang</p><label className="library-folder-select">Thư mục<select value={document.folder_id || ""} disabled={busy} onChange={(event) => mutate(() => request(`/api/v1/projects/${projectId}/documents/${document.document_id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder_id: event.target.value || null, expected_version: document.version }) }))}><option value="">Chưa phân loại</option>{folders.map((folder) => <option value={folder.id} key={folder.id}>{folder.name}</option>)}</select></label></article>)}</div>}</section>
      </div>}
    </main>
    <LibraryDialog dialog={dialog} busy={busy} onClose={() => setDialog(null)} onConfirm={confirmDialog} />
  </div>;
}
