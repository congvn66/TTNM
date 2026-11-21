from __future__ import annotations

from uuid import UUID

from report_qa.api.library import (
    FolderCreateRequest,
    ProjectCreateRequest,
    ProjectDocumentUpdateRequest,
    SessionProjectUpdateRequest,
)
from report_qa.api.library import router as library_router
from report_qa.api.devices import router as device_router
from report_qa.api.main import app


def test_project_and_document_payloads_have_server_safe_constraints() -> None:
    project = ProjectCreateRequest(name="  Q1 review  ")
    assert project.name == "  Q1 review  "

    document = ProjectDocumentUpdateRequest(
        folder_id=UUID("11111111-1111-1111-1111-111111111111"),
        display_name="report.pdf",
        expected_version=3,
    )
    assert document.expected_version == 3

    session_move = SessionProjectUpdateRequest(project_id=UUID("22222222-2222-2222-2222-222222222222"))
    assert isinstance(session_move.project_id, UUID)


def test_folder_payload_rejects_empty_name() -> None:
    try:
        FolderCreateRequest(name=" ")
    except ValueError:
        return
    raise AssertionError("blank folder names must be rejected")


def test_project_library_and_device_routes_are_registered() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods or [])))
        for router in (library_router, device_router)
        for route in router.routes
    }
    assert any(path == "/api/v1/projects" and "GET" in methods for path, methods in routes)
    assert any(path == "/api/v1/projects/{project_id}/library" and "GET" in methods for path, methods in routes)
    assert any(path == "/api/v1/sessions/{session_id}/project" and "PATCH" in methods for path, methods in routes)
    assert any(path == "/api/v1/auth/sessions" and "GET" in methods for path, methods in routes)
    assert any(path == "/api/v1/auth/sessions/{session_id}" and "DELETE" in methods for path, methods in routes)
    assert any(path == "/api/v1/auth/sessions/revoke-others" and "POST" in methods for path, methods in routes)
