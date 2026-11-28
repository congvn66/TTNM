import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../../shared/api/client.js";
import { DropOverlay, Toasts } from "../reader/Chrome.jsx";
import { Icon } from "../reader/Icon.jsx";
import { useReports } from "../reader/useReports.js";
import { ActionDialog } from "./Dialog.jsx";
import { matchesQuery } from "./search.js";
import { WorkspaceShell } from "./WorkspaceShell.jsx";

const PROJECT_KEY = "sourcelens-library-project";
const MAX_BYTES = 100 * 1024 * 1024;
// A ready report shows no chip.
const STATUS_LABEL = { queued: "Đang chờ", processing: "Đang đọc", failed: "Không đọc được" };
const JSON_HEADERS = { "Content-Type": "application/json" };
const formatBytes = (value = 0) => value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toLocaleString("vi-VN", { maximumFractionDigits: 1 })} MB`;

function readStored(key) { try { return localStorage.getItem(key); } catch { return null; } }
function writeStored(key, value) { try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch { /* storage blocked */ } }

function NavItem({ selected, onClick, label, count, title }) {
  return <li><button type="button" className={`ws-nav-item${selected ? " selected" : ""}`} aria-current={selected ? "true" : undefined} title={title ?? label} onClick={onClick}>
    <span className="ws-nav-label">{label}</span>{count !== undefined && <small>{count}</small>}
  </button></li>;
}

function NavGroup({ title, addLabel, onAdd, children }) {
  return <div className="ws-nav-group">
    <div className="ws-nav-head"><span>{title}</span><button type="button" className="ws-mini" aria-label={addLabel} title={addLabel} onClick={onAdd}><Icon name="plus" size={15} /></button></div>
    <ul>{children}</ul>
  </div>;
}

/** Projects and folders of the account, with their reports as cards. Uploads here go into the selected project. */
export default function LibraryScreen({ user = null, onSignOut = null, onNavigate }) {
  const reports = useReports({ user, syncUrl: false });
  const [projects, setProjects] = useState(null);
  const [projectId, setProjectId] = useState(null);
  const [library, setLibrary] = useState({ projectId: null, data: null });
  const [query, setQuery] = useState("");
  const [folderId, setFolderId] = useState("all");
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [uploading, setUploading] = useState(null);
  const [toasts, setToasts] = useState([]);
  const librarySeq = useRef(0);
  const uploadRef = useRef(null);

  const toast = useCallback((item) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((list) => [...list.slice(-2), { ...item, id }]);
    window.setTimeout(() => setToasts((list) => list.filter((entry) => entry.id !== id)), item.kind === "error" ? 9000 : 5000);
  }, []);

  const loadProjects = useCallback(async () => {
    const body = await request("/api/v1/projects");
    const list = body.projects ?? [];
    setProjects(list);
    return list;
  }, []);

  // Only the newest request may fill the page, so a slow answer for an earlier project never shows under a later one.
  const loadLibrary = useCallback(async (id) => {
    const seq = ++librarySeq.current;
    const data = await request(`/api/v1/projects/${id}/library`);
    if (seq === librarySeq.current) setLibrary({ projectId: id, data });
    return data;
  }, []);

  const selectProject = useCallback((id) => {
    setProjectId(id); writeStored(PROJECT_KEY, id); setFolderId("all");
    if (!id) return Promise.resolve(null);
    return loadLibrary(id);
  }, [loadLibrary]);

  // First load: the remembered project's reports are asked for at the same time as the project list.
  const start = useCallback(async () => {
    setError(null);
    const stored = readStored(PROJECT_KEY);
    const early = stored ? loadLibrary(stored).catch(() => null) : null;
    try {
      const list = await loadProjects();
      const chosen = list.find((item) => item.id === stored)?.id ?? list[0]?.id ?? null;
      setProjectId(chosen); writeStored(PROJECT_KEY, chosen);
      if (chosen && (chosen !== stored || !(await early))) await loadLibrary(chosen);
    } catch (reason) {
      setError({ message: reason.message, retry: start });
    }
  }, [loadLibrary, loadProjects]);
  useEffect(() => { start(); }, [start]);

  const refresh = useCallback(async () => {
    setError(null);
    try { await Promise.all([loadProjects(), projectId ? loadLibrary(projectId) : null]); }
    catch (reason) { setError({ message: reason.message, retry: refresh }); }
  }, [loadLibrary, loadProjects, projectId]);

  const project = projects?.find((item) => item.id === projectId) ?? null;
  const current = library.projectId === projectId ? library.data : null;
  const switching = Boolean(projectId) && !current;
  const folders = current?.folders ?? [];
  const folder = folders.find((item) => item.id === folderId) ?? null;
  useEffect(() => { if (current && folderId !== "all" && folderId !== "unfiled" && !folder) setFolderId("all"); }, [current, folderId, folder]);

  // Name, status and page count come from the reader's list when it has the report:
  // its status is polled while a report is being read, and its name follows a rename in the reader.
  const documents = useMemo(() => {
    const byId = new Map(reports.reports.map((report) => [report.id, report]));
    return (current?.documents ?? []).map((document) => {
      const report = byId.get(document.document_id);
      return { ...document, report, name: report?.file_name || document.display_name || document.file_name || document.title || "Báo cáo", status: report?.extraction_status ?? document.extraction_status, pages: report?.page_count ?? document.page_count };
    });
  }, [current, reports.reports]);
  const counts = useMemo(() => {
    const byFolder = new Map();
    documents.forEach((document) => byFolder.set(document.folder_id ?? "unfiled", (byFolder.get(document.folder_id ?? "unfiled") ?? 0) + 1));
    return byFolder;
  }, [documents]);
  const inFolder = documents.filter((document) => folderId === "all" || (folderId === "unfiled" ? !document.folder_id : document.folder_id === folderId));
  const shown = inFolder.filter((document) => matchesQuery(document.name, query));

  function openDocument(document) {
    if (!document.report) return;
    reports.select(document.document_id);
    onNavigate?.(`/?r=${encodeURIComponent(document.document_id)}`);
  }

  async function moveToFolder(document, nextFolderId) {
    setError(null);
    try {
      await request(`/api/v1/projects/${projectId}/documents/${document.document_id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ folder_id: nextFolderId || null, expected_version: document.version }) });
      await loadLibrary(projectId);
    } catch (reason) { setError({ message: reason.message, retry: refresh }); }
  }

  async function uploadFile(file) {
    if (!file || !project || !current) return;
    if (!(file.type === "application/pdf" || /\.pdf$/i.test(file.name ?? ""))) { toast({ kind: "error", text: "Chỉ nhận tệp PDF." }); return; }
    if (file.size > MAX_BYTES) { toast({ kind: "error", text: "Tệp lớn hơn 100 MB." }); return; }
    const id = project.id;
    setUploading({ name: file.name, projectId: id, documentId: null });
    try {
      // The server files the report in this project (its newest chat, or a new one).
      const form = new FormData();
      form.append("file", file);
      const result = await request(`/api/v1/projects/${id}/documents`, { method: "POST", body: form });
      setUploading((current) => current && { ...current, documentId: result.document?.id ?? null });
      toast({ text: `Đang đọc ${result.document?.file_name ?? file.name}…` });
      await Promise.all([loadLibrary(id), loadProjects(), reports.reload()]);
    } catch (reason) {
      toast({ kind: "error", text: reason.message, action: { label: "Thử lại", onClick: () => uploadFile(file) } });
    } finally { setUploading(null); }
  }
  const pickFile = () => uploadRef.current?.click();

  const createProject = () => setDialog({ title: "Tạo dự án", value: "", confirmLabel: "Tạo", busyLabel: "Đang tạo…", onConfirm: async (name) => {
    const body = await request("/api/v1/projects", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ name }) });
    await loadProjects();
    await selectProject(body.project.id);
  } });
  const renameProject = () => project && setDialog({ title: "Đổi tên dự án", value: project.name, confirmLabel: "Lưu", onConfirm: async (name) => {
    await request(`/api/v1/projects/${project.id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ name }) });
    await loadProjects();
  } });
  const deleteProject = () => {
    if (!project) return;
    const count = documents.length;
    if (count) { setDialog({ title: `Chưa xóa được “${project.name}”`, text: `Dự án còn ${count} báo cáo. Chỉ xóa được dự án trống.` }); return; }
    setDialog({ title: `Xóa dự án “${project.name}”?`, text: "Dự án trống này sẽ bị xóa.", confirmLabel: "Xóa", busyLabel: "Đang xóa…", danger: true, onConfirm: async () => {
      await request(`/api/v1/projects/${project.id}`, { method: "DELETE" });
      const list = await loadProjects();
      await selectProject(list[0]?.id ?? null);
    } });
  };
  const createFolder = () => project && setDialog({ title: "Tạo thư mục", value: "", confirmLabel: "Tạo", busyLabel: "Đang tạo…", onConfirm: async (name) => {
    const body = await request(`/api/v1/projects/${project.id}/folders`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ name }) });
    await loadLibrary(project.id);
    if (body.folder?.id) setFolderId(body.folder.id);
  } });
  const renameFolder = () => folder && setDialog({ title: "Đổi tên thư mục", value: folder.name, confirmLabel: "Lưu", onConfirm: async (name) => {
    await request(`/api/v1/folders/${folder.id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ name, expected_version: folder.version }) });
    await loadLibrary(projectId);
  } });
  const deleteFolder = () => folder && setDialog({ title: `Xóa thư mục “${folder.name}”?`, text: "Báo cáo trong thư mục sẽ chuyển về Chưa phân loại.", confirmLabel: "Xóa", busyLabel: "Đang xóa…", danger: true, onConfirm: async () => {
    await request(`/api/v1/folders/${folder.id}`, { method: "DELETE" });
    setFolderId("all");
    await loadLibrary(projectId);
  } });

  const loadingAll = projects === null && !error;
  // The upload card gives way to the report's own card as soon as the list has it.
  const uploadingHere = uploading && uploading.projectId === projectId && !documents.some((document) => document.document_id === uploading.documentId);

  async function retryReading(document) {
    try {
      await request(`/api/v1/sessions/${document.report.sessionId}/documents/${document.document_id}/extraction`, { method: "POST" });
      toast({ text: `Đang đọc lại ${document.name}…` });
      await reports.reload();
    } catch (reason) { toast({ kind: "error", text: reason.message }); }
  }

  return <WorkspaceShell page="library" title="Thư viện" reports={reports} user={user} onNavigate={onNavigate} onSignOut={onSignOut} onUpload={() => { if (project && current) pickFile(); }}>
    <input ref={uploadRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => { uploadFile(event.target.files?.[0]); event.target.value = ""; }} />
    <div className="ws-page ws-library">
      {error && <div className="ws-notice" role="alert"><span>{error.message}</span><button type="button" className="rd-button" onClick={() => error.retry()}>Thử lại</button></div>}
      {loadingAll ? <div className="ws-state" role="status"><span className="rd-spinner" aria-hidden="true" />Đang tải thư viện…</div> : projects && <div className="ws-lib">
        <aside className="ws-lib-nav" aria-label="Dự án và thư mục">
          <NavGroup title="Dự án" addLabel="Tạo dự án" onAdd={createProject}>
            {projects.map((item) => <NavItem key={item.id} selected={item.id === projectId} label={item.name} count={item.document_count} onClick={() => { if (item.id !== projectId) selectProject(item.id).catch((reason) => setError({ message: reason.message, retry: refresh })); }} />)}
          </NavGroup>
          {current && <NavGroup title="Thư mục" addLabel="Tạo thư mục" onAdd={createFolder}>
            <NavItem selected={folderId === "all"} label="Tất cả" count={documents.length} onClick={() => setFolderId("all")} />
            <NavItem selected={folderId === "unfiled"} label="Chưa phân loại" count={counts.get("unfiled") ?? 0} onClick={() => setFolderId("unfiled")} />
            {folders.map((item) => <NavItem key={item.id} selected={folderId === item.id} label={item.name} count={counts.get(item.id) ?? 0} onClick={() => setFolderId(item.id)} />)}
          </NavGroup>}
        </aside>

        <section className="ws-lib-main" aria-busy={switching}>
          {project && <header className="ws-lib-head">
            <div className="ws-lib-title"><h2 title={project.name}>{project.name}</h2><p>{switching ? "Đang tải…" : `${documents.length} báo cáo`}</p></div>
            <div className="ws-lib-actions">
              <button type="button" className="rd-button" disabled={!current || Boolean(uploading)} onClick={pickFile}><Icon name="upload" size={16} />Tải lên</button>
              <button type="button" className="rd-button" onClick={renameProject}>Đổi tên</button>
              <button type="button" className="rd-button ws-danger" onClick={deleteProject} disabled={!current}>Xóa</button>
            </div>
          </header>}

          {folder && <div className="ws-folder-bar">
            <Icon name="folder" size={16} /><b title={folder.name}>{folder.name}</b>
            <span className="ws-folder-actions"><button type="button" className="rd-link" onClick={renameFolder}>Đổi tên</button><button type="button" className="rd-link ws-danger-link" onClick={deleteFolder}>Xóa thư mục</button></span>
          </div>}

          {current && documents.length > 0 && <div className="ws-lib-tools">
            <label className="ws-search"><Icon name="search" size={15} /><input type="search" aria-label="Tìm báo cáo" placeholder="Tìm báo cáo" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            {query.trim() && <span className="ws-result-count" role="status">{shown.length} kết quả</span>}
          </div>}

          {switching ? <div className="ws-grid" aria-hidden="true">{[0, 1, 2].map((key) => <div key={key} className="ws-card ws-card-skeleton" />)}</div>
            : !project ? <div className="ws-state"><b>Chưa có dự án</b><button type="button" className="rd-button primary" onClick={createProject}>Tạo dự án</button></div>
            : <>
              {(shown.length > 0 || uploadingHere) && <div className="ws-grid">
                {uploadingHere && <article className="ws-card ws-card-uploading" role="status"><span className="ws-card-icon"><span className="rd-spinner" aria-hidden="true" /></span><span className="ws-card-name">{uploading.name}</span><span className="ws-card-meta">Đang tải lên…</span></article>}
                {shown.map((document) => <article className="ws-card" key={document.document_id}>
                  <button type="button" className="ws-card-open" disabled={!document.report} onClick={() => openDocument(document)} title={document.name}>
                    <span className="ws-card-icon" aria-hidden="true"><Icon name="file" size={18} /></span>
                    <span className="ws-card-name">{document.name}</span>
                    <span className="ws-card-meta">
                      <span>{formatBytes(document.byte_size)} · {document.pages ?? "?"} trang</span>
                      {STATUS_LABEL[document.status] && <span className={`ws-chip ${document.status}`}><span className={`rd-dot ${document.status}`} aria-hidden="true" />{STATUS_LABEL[document.status]}</span>}
                    </span>
                  </button>
                  {document.status === "failed" && document.report?.can_retry && <div className="ws-card-retry"><button type="button" className="ws-retry" onClick={() => retryReading(document)}>Thử lại</button></div>}
                  <label className="ws-card-folder"><span>Thư mục</span><select className="ws-input" value={document.folder_id || ""} onChange={(event) => moveToFolder(document, event.target.value)}><option value="">Chưa phân loại</option>{folders.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
                </article>)}
              </div>}
              {!shown.length && !uploadingHere && (documents.length === 0
                ? <div className="ws-state"><b>Chưa có báo cáo trong dự án này</b><button type="button" className="rd-button primary" onClick={pickFile} disabled={Boolean(uploading)}><Icon name="upload" size={16} />Tải lên</button></div>
                : query.trim() ? <div className="ws-state"><b>Không có kết quả</b></div>
                : <div className="ws-state"><b>{folderId === "unfiled" ? "Mọi báo cáo đã có thư mục" : "Thư mục trống"}</b></div>)}
            </>}
        </section>
      </div>}
    </div>
    <ActionDialog dialog={dialog} onClose={() => setDialog(null)} />
    <Toasts toasts={toasts} onClose={(id) => setToasts((list) => list.filter((entry) => entry.id !== id))} />
    {project && current && <DropOverlay onFile={uploadFile} />}
  </WorkspaceShell>;
}
