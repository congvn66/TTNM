from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from report_qa.application.flows import AnswerFlow, EvidenceFlow, ExtractionFlow, QuestionFlow, UploadFlow
from report_qa.domain.errors import ConflictError, InvariantError, NotFoundError
from report_qa.domain.contracts import validate_provider_payload
from report_qa.domain.service import decimal_sum, growth_rate
from report_qa.domain.schema import validate_table_inventory
from report_qa.domain.types import AnswerStatus, DataStatus, EvidenceAction, JobStatus, ValueKind
from report_qa.domain.models import Chat, Document
from report_qa.infrastructure.memory import InMemoryDataRepository
from report_qa.worker.handlers import WorkerHandlers


class DataFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryDataRepository()
        self.owner_id = uuid4()
        self.document_id = uuid4()
        self.chat_id = uuid4()
        self.repo.add_document(Document(id=self.document_id, owner_id=self.owner_id, title="Test report"))
        self.repo.add_chat(Chat(id=self.chat_id, owner_id=self.owner_id))

    def test_upload_extract_question_publish_and_edit_recalculate(self) -> None:
        semantic = {
            "schema_version": 1,
            "measure": {"code": "revenue", "label": "Doanh thu"},
            "subject": None,
            "unit": None,
            "period": {
                "status": "unspecified",
                "label": None,
                "start": None,
                "end": None,
                "basis": None,
                "source_region_ids": [],
            },
            "dimensions": {},
            "value_operator": "eq",
        }
        upload = UploadFlow(self.repo).start(
            owner_id=self.owner_id,
            document_id=self.document_id,
            file_name="bao-cao.pdf",
            file_hash="sha256:test",
            byte_size=100,
            idempotency_key="upload-1",
        )
        regions, evidences = ExtractionFlow(self.repo).complete(
            extraction_run_id=upload.extraction_run_id,
            extractor_name="fake",
            extractor_version="1",
            regions=[{"region_key": "r1", "page_number": 1, "region_type": "table", "bbox": [0, 0, 0.5, 0.5]}],
            evidences=[
                {
                    "evidence_key": "e1",
                    "source_region_key": "r1",
                    "value_kind": "number",
                    "data_status": "valid",
                    "raw_value": "0",
                    "semantic": semantic,
                }
            ],
        )
        self.assertEqual(len(regions), 1)
        chat_source = ExtractionFlow(self.repo).switch_source(
            owner_id=self.owner_id,
            chat_id=self.chat_id,
            document_version_id=upload.document_version_id,
            extraction_run_id=upload.extraction_run_id,
        )
        with self.assertRaises(NotFoundError):
            ExtractionFlow(self.repo).attach_evidence(
                owner_id=self.owner_id,
                chat_id=self.chat_id,
                chat_source_id=uuid4(),
                extracted_evidence_id=evidences[0],
            )
        chat_evidence = ExtractionFlow(self.repo).attach_evidence(
            owner_id=self.owner_id,
            chat_id=self.chat_id,
            chat_source_id=chat_source.id,
            extracted_evidence_id=evidences[0],
        )
        accepted = QuestionFlow(self.repo).submit(
            owner_id=self.owner_id,
            chat_id=self.chat_id,
            question="Doanh thu là bao nhiêu?",
            idempotency_key="question-1",
        )
        WorkerHandlers(self.repo).claim(job_id=accepted.job_id, lease_token="lease-1")
        first_revision = AnswerFlow(self.repo).publish(
            job_id=accepted.job_id,
            lease_token="lease-1",
            status=AnswerStatus.ANSWERED,
            structured_result={"value": "0"},
            rendered_text="0",
            evidence_revision_ids=[chat_evidence.current_revision_id],
        )
        changed = EvidenceFlow(self.repo).apply_revision(
            owner_id=self.owner_id,
            chat_evidence_id=chat_evidence.id,
            expected_revision_id=chat_evidence.current_revision_id,
            action=EvidenceAction.EDIT,
            value_kind=ValueKind.NUMBER,
            data_status=DataStatus.VALID,
            semantic=semantic,
            raw_value="58",
            reason="Sửa theo bảng gốc",
        )
        self.assertEqual(changed.affected_message_ids, (accepted.assistant_message_id,))
        recalc_job = self.repo.state.jobs[changed.recalculate_job_ids[0]]
        WorkerHandlers(self.repo).claim(job_id=recalc_job.id, lease_token="lease-2")
        second_revision = AnswerFlow(self.repo).publish(
            job_id=recalc_job.id,
            lease_token="lease-2",
            status=AnswerStatus.ANSWERED,
            structured_result={"value": "58"},
            rendered_text="58",
            evidence_revision_ids=[changed.revision_id],
        )
        self.assertNotEqual(first_revision.id, second_revision.id)
        self.assertEqual(self.repo.state.messages[accepted.assistant_message_id].needs_update, False)

    def test_stale_revision_and_invalid_payload_are_rejected(self) -> None:
        upload = UploadFlow(self.repo).start(
            owner_id=self.owner_id,
            document_id=self.document_id,
            file_name="bao-cao.pdf",
            file_hash="hash",
            byte_size=10,
            idempotency_key="same",
        )
        self.assertEqual(
            upload,
            UploadFlow(self.repo).start(
                owner_id=self.owner_id,
                document_id=self.document_id,
                file_name="bao-cao.pdf",
                file_hash="hash",
                byte_size=10,
                idempotency_key="same",
            ),
        )
        with self.assertRaises(ConflictError):
            UploadFlow(self.repo).start(
                owner_id=self.owner_id,
                document_id=self.document_id,
                file_name="bao-cao.pdf",
                file_hash="hash",
                byte_size=11,
                idempotency_key="same",
            )
        with self.assertRaises(InvariantError):
            ExtractionFlow(self.repo).complete(
                extraction_run_id=upload.extraction_run_id,
                extractor_name="fake",
                regions=[{"region_key": "r1", "page_number": 1, "region_type": "table", "bbox": [0, 0, 1, 1]}],
                evidences=[
                    {
                        "source_region_key": "r1",
                        "value_kind": "number",
                        "data_status": "valid",
                        "raw_value": "NaN",
                        "semantic": {},
                    }
                ],
            )
        self.assertEqual(self.repo.get_extraction_run(upload.extraction_run_id).status.value, "failed")

    def test_deterministic_decimal_rules_keep_zero_distinct(self) -> None:
        self.assertEqual(decimal_sum(["0", "2.50"]), "2.50")
        self.assertIsNone(growth_rate("0", "5"))
        with self.assertRaises(InvariantError):
            decimal_sum(["NaN"])

    def test_contract_inventory_source_switch_and_job_events(self) -> None:
        validate_table_inventory()
        semantic = {
            "schema_version": 1,
            "measure": {"code": "revenue", "label": "Doanh thu"},
            "subject": None,
            "unit": None,
            "period": {"status": "unspecified", "label": None, "start": None, "end": None, "basis": None, "source_region_ids": []},
            "dimensions": {},
            "value_operator": "eq",
        }
        upload = UploadFlow(self.repo).start(
            owner_id=self.owner_id,
            document_id=self.document_id,
            file_name="report.pdf",
            file_hash="h1",
            byte_size=20,
            idempotency_key="u1",
        )
        ExtractionFlow(self.repo).complete(
            extraction_run_id=upload.extraction_run_id,
            extractor_name="fake",
            regions=[{"region_key": "r1", "page_number": 1, "region_type": "paragraph", "bbox": None}],
            evidences=[
                {
                    "evidence_key": "e1",
                    "source_region_key": "r1",
                    "value_kind": "text",
                    "data_status": "valid",
                    "raw_text": "ok",
                    "semantic": semantic,
                }
            ],
        )
        source = ExtractionFlow(self.repo).switch_source(
            owner_id=self.owner_id,
            chat_id=self.chat_id,
            document_version_id=upload.document_version_id,
            extraction_run_id=upload.extraction_run_id,
        )
        self.assertEqual(source.source_status, "active")
        self.assertEqual(self.repo.state.chats[self.chat_id].data_revision, 1)
        WorkerHandlers(self.repo).claim(job_id=upload.job_id, lease_token="upload-lease")
        WorkerHandlers(self.repo).heartbeat(job_id=upload.job_id, lease_token="upload-lease", progress=50)
        WorkerHandlers(self.repo).fail(job_id=upload.job_id, lease_token="upload-lease", error_code="provider_timeout")
        self.assertEqual([event.event_type for event in self.repo.state.job_events[upload.job_id]], ["started", "progress", "failed"])

    def test_provider_contract_rejects_unknown_region_and_transaction_rolls_back(self) -> None:
        with self.assertRaises(InvariantError):
            validate_provider_payload(
                {
                    "schema_version": 1,
                    "regions": [],
                    "evidences": [
                        {
                            "evidence_key": "e1",
                            "source_region_key": "missing",
                            "value_kind": "number",
                            "raw_value": "1",
                            "raw_text": None,
                            "semantic": {},
                            "data_status": "valid",
                            "extraction_method": "table",
                            "confidence": 1,
                        }
                    ],
                    "warnings": [],
                }
            )
        original_revision = self.repo.state.chats[self.chat_id].data_revision
        with self.assertRaises(RuntimeError):
            with self.repo.transaction():
                self.repo.state.chats[self.chat_id].data_revision = 99
                raise RuntimeError("rollback")
        self.assertEqual(self.repo.state.chats[self.chat_id].data_revision, original_revision)


if __name__ == "__main__":
    unittest.main()
