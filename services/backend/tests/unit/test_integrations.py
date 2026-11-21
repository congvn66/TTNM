from report_qa.infrastructure.integrations import readiness, runtime_capabilities


def test_runtime_capabilities_reports_optional_backend_without_loading_models(monkeypatch):
    monkeypatch.setenv("PDF_EXTRACTION_BACKEND", "docling")
    monkeypatch.setenv("CHART_READER_BACKEND", "deplot")
    monkeypatch.setenv("REPORT_QA_AI_MODE", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")

    result = runtime_capabilities(
        database={"backend": "postgres", "status": "ok"},
        storage={"backend": "r2", "status": "ok"},
    )

    assert result["ai"] == {
        "selected": "openrouter",
        "model": "openai/gpt-6-luna",
        "status": "configured",
        "network_probe": "not_run",
    }
    assert result["pdf_extraction"]["selected"] == "docling"
    assert result["chart_reader"]["selected"] == "deplot"
    assert result["chart_reader"]["weights"].startswith("lazy")


def test_readiness_keeps_text_ready_when_on_demand_chart_dependency_is_missing():
    capabilities = {
        "ai": {"status": "available"},
        "pdf_extraction": {"status": "available"},
        "chart_reader": {"status": "missing_dependency"},
        "database": {"status": "disabled"},
        "storage": {"backend": "local", "status": "ok"},
    }

    assert readiness(capabilities) == ("ready", [])


def test_readiness_exposes_selected_external_adapter_blockers():
    capabilities = {
        "ai": {"status": "configured"},
        "pdf_extraction": {"status": "missing_dependency"},
        "chart_reader": {"status": "available"},
        "database": {"status": "unavailable"},
        "storage": {"status": "unavailable"},
    }

    state, blockers = readiness(capabilities)
    assert state == "degraded"
    assert blockers == ["pdf_extraction:missing_dependency", "database:unavailable", "storage:unavailable"]
