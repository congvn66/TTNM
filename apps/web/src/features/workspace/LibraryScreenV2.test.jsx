/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("../../shared/api/client.js", () => ({ request: requestMock }));

import LibraryScreen from "./LibraryScreenV2.jsx";

const emptyLibrary = { folders: [], documents: [], sessions: [] };

describe("Library project flow", () => {
  afterEach(() => {
    cleanup();
    requestMock.mockReset();
  });

  it("selects a project immediately after creating it", async () => {
    let created = false;
    requestMock.mockImplementation((path, options = {}) => {
      if (path === "/api/v1/projects" && options.method === "POST") {
        created = true;
        return Promise.resolve({ project: { id: "project-new", name: "Project mới", session_count: 0, document_count: 0 } });
      }
      if (path === "/api/v1/projects") {
        const projects = [{ id: "project-old", name: "Project cũ", session_count: 0, document_count: 0 }];
        if (created) projects.push({ id: "project-new", name: "Project mới", session_count: 0, document_count: 0 });
        return Promise.resolve({ projects });
      }
      if (path.endsWith("/library")) return Promise.resolve(emptyLibrary);
      return Promise.resolve({});
    });

    render(<LibraryScreen onNavigate={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByText("Project cũ").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByRole("button", { name: "Tạo project" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Lưu thay đổi" }));

    await waitFor(() => expect(requestMock).toHaveBeenCalledWith("/api/v1/projects/project-new/library"));
  });
});
