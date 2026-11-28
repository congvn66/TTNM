/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const { requestMock, reportsState } = vi.hoisted(() => ({ requestMock: vi.fn(), reportsState: { reports: [] } }));
vi.mock("../../shared/api/client.js", () => ({ request: requestMock }));
vi.mock("../reader/useReports.js", () => ({ useReports: () => ({ reports: reportsState.reports, select: vi.fn(), reload: vi.fn(() => Promise.resolve()) }) }));

import LibraryScreen from "./LibraryScreenV2.jsx";
import { ThemeProvider } from "../theme/ThemeProvider.jsx";

const doc = (id, name, extra = {}) => ({ document_id: id, display_name: name, file_name: name, byte_size: 2048, page_count: 3, version: 1, folder_id: null, extraction_status: "completed", session_id: "s1", ...extra });

function fakeServer() {
  const db = {
    projects: [{ id: "p1", name: "Báo cáo của tôi", document_count: 2 }, { id: "p2", name: "Dự án trống", document_count: 0 }],
    libraries: {
      p1: { folders: [], sessions: [{ id: "s1" }], documents: [doc("d1", "bao-cao-mau-huong-lua.pdf"), doc("d2", "bctc-q3-2025.pdf")] },
      p2: { folders: [], sessions: [], documents: [] },
    },
  };
  requestMock.mockImplementation(async (path, options = {}) => {
    const method = options.method ?? "GET";
    if (path === "/api/v1/projects" && method === "GET") return { projects: db.projects };
    if (path === "/api/v1/projects" && method === "POST") {
      const project = { id: "p3", name: JSON.parse(options.body).name, document_count: 0 };
      db.projects = [project, ...db.projects]; db.libraries.p3 = { folders: [], sessions: [], documents: [] };
      return { project };
    }
    const library = path.match(/^\/api\/v1\/projects\/(\w+)\/library$/);
    if (library) return { project: { id: library[1] }, ...db.libraries[library[1]] };
    if (path === "/api/v1/projects/p2/documents" && method === "POST") { db.libraries.p2.documents = [doc("d9", "moi.pdf", { extraction_status: "queued" })]; return { session_id: "s-new", document: { id: "d9", file_name: "moi.pdf" } }; }
    if (path === "/api/v1/sessions/s1/documents/d2/extraction" && method === "POST") return { job: {} };
    throw new Error(`unexpected ${method} ${path}`);
  });
  return db;
}

const renderLibrary = () => render(<ThemeProvider><LibraryScreen user={{ id: "u", display_name: "A", email: "a@b.vn" }} onNavigate={vi.fn()} /></ThemeProvider>);

describe("Library", () => {
  beforeEach(() => { localStorage.clear(); reportsState.reports = []; });
  afterEach(() => { cleanup(); requestMock.mockReset(); });

  it("selects a new project after creating it, and remembers it", async () => {
    fakeServer();
    renderLibrary();
    await screen.findByText("bctc-q3-2025.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Tạo dự án" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Tên"), { target: { value: "Quý 4" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Tạo" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.querySelector(".ws-lib-title h2").textContent).toBe("Quý 4");
    expect(localStorage.getItem("sourcelens-library-project")).toBe("p3");
  });

  it("keeps the dialog open with the error and the typed name when the request fails", async () => {
    fakeServer();
    renderLibrary();
    await screen.findByText("bctc-q3-2025.pdf");
    const base = requestMock.getMockImplementation();
    requestMock.mockImplementation((path, options = {}) => (path === "/api/v1/projects" && options.method === "POST" ? Promise.reject(new Error("Tên dự án đã tồn tại.")) : base(path, options)));
    fireEvent.click(screen.getByRole("button", { name: "Tạo dự án" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Tên"), { target: { value: "Báo cáo của tôi" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Tạo" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("Tên dự án đã tồn tại.");
    expect(within(dialog).getByLabelText("Tên").value).toBe("Báo cáo của tôi");
    expect(within(dialog).getByRole("button", { name: "Thử lại" })).toBeTruthy();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("finds reports without accents and with spaces for hyphens", async () => {
    fakeServer();
    renderLibrary();
    await screen.findByText("bctc-q3-2025.pdf");
    fireEvent.change(screen.getByLabelText("Tìm báo cáo"), { target: { value: "hương lúa" } });
    expect(screen.getByText("bao-cao-mau-huong-lua.pdf")).toBeTruthy();
    expect(screen.queryByText("bctc-q3-2025.pdf")).toBeNull();
    expect(screen.getByText("1 kết quả")).toBeTruthy();
  });

  it("shows the reader's name and live status for a report", async () => {
    fakeServer();
    reportsState.reports = [{ id: "d2", file_name: "doi-ten.pdf", extraction_status: "processing", page_count: 3 }];
    renderLibrary();
    expect(await screen.findByText("doi-ten.pdf")).toBeTruthy();
    expect(screen.getByText("Đang đọc")).toBeTruthy();
  });

  it("offers Thử lại on a failed reading the server can retry", async () => {
    fakeServer();
    reportsState.reports = [{ id: "d2", sessionId: "s1", file_name: "bctc-q3-2025.pdf", extraction_status: "failed", can_retry: true }];
    renderLibrary();
    await screen.findByText("Không đọc được");
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(requestMock).toHaveBeenCalledWith("/api/v1/sessions/s1/documents/d2/extraction", { method: "POST" }));
  });

  it("files an upload in the selected project through the project upload", async () => {
    fakeServer();
    localStorage.setItem("sourcelens-library-project", "p2");
    renderLibrary();
    await screen.findByText("Chưa có báo cáo trong dự án này");
    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input, { target: { files: [new File(["%PDF-1.4"], "moi.pdf", { type: "application/pdf" })] } });
    expect(await screen.findByText("moi.pdf")).toBeTruthy();
    const [, options] = requestMock.mock.calls.find(([path]) => path === "/api/v1/projects/p2/documents");
    expect(options.method).toBe("POST");
    expect(options.body.get("file").name).toBe("moi.pdf");
    expect(document.querySelector(".ws-card-uploading")).toBeNull();
  });
});
