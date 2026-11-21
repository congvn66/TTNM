from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from report_qa.domain.errors import ConflictError
from report_qa.domain.models import Chat, Document, Job
from report_qa.domain.types import JobStatus
from report_qa.infrastructure.memory import InMemoryDataRepository


class RepositoryContractTests(unittest.TestCase):
    def test_typed_repository_surface_and_idempotency_hash(self) -> None:
        repo = InMemoryDataRepository()
        required = (
            "transaction",
            "get_document",
            "save_document_version",
            "get_extraction_run",
            "save_extraction_run",
            "get_chat",
            "save_chat",
            "get_job",
            "add_job",
            "add_job_event",
        )
        for name in required:
            self.assertTrue(callable(getattr(repo, name)), name)

        owner_id = uuid4()
        repo.add_document(Document(id=uuid4(), owner_id=owner_id, title="Contract"))
        repo.add_chat(Chat(id=uuid4(), owner_id=owner_id))
        repo.put_request(owner_id, "POST /test", "key", "hash-1", {"id": "one"})
        self.assertEqual(repo.get_request(owner_id, "POST /test", "key", "hash-1"), {"id": "one"})
        with self.assertRaises(ConflictError):
            repo.get_request(owner_id, "POST /test", "key", "hash-2")

    def test_job_dedup_and_transaction_rollback(self) -> None:
        repo = InMemoryDataRepository()
        owner_id = uuid4()
        first = Job(
            id=uuid4(),
            owner_id=owner_id,
            job_type="answer_question",
            status=JobStatus.QUEUED,
            input_data_revision=0,
            idempotency_key="dedup-1",
        )
        second = Job(
            id=uuid4(),
            owner_id=owner_id,
            job_type="answer_question",
            status=JobStatus.QUEUED,
            input_data_revision=0,
            idempotency_key="dedup-1",
        )
        self.assertIs(repo.add_job(first), first)
        self.assertIs(repo.add_job(second), first)
        with self.assertRaises(RuntimeError):
            with repo.transaction():
                repo.add_job_event(first.id, "started")
                raise RuntimeError("fault injection")
        self.assertNotIn(first.id, repo.state.job_events)


if __name__ == "__main__":
    unittest.main()

