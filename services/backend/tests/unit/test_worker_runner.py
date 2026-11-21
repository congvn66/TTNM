from types import SimpleNamespace


def test_worker_uses_stable_environment_identity(monkeypatch):
    from report_qa.worker import runner

    calls = []

    class FakeQueue:
        def __init__(self, database_url):
            self.database_url = database_url

        def claim(self, *, worker_id):
            calls.append(worker_id)
            return None

    monkeypatch.setattr(runner, "PostgresJobQueue", FakeQueue)
    monkeypatch.setattr(runner, "settings", SimpleNamespace(persistence_backend="postgres", database_url="test"))
    monkeypatch.setenv("SOURCELENS_WORKER_ID", "deployment-worker-a")

    runner.run(once=True)

    assert calls == ["deployment-worker-a"]

