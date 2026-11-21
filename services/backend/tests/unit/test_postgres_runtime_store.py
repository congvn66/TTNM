from uuid import uuid4

from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore


def test_catalog_owner_match_accepts_json_string_and_uuid_forms():
    owner = uuid4()

    assert PostgresRuntimeStore._owner_matches(str(owner), owner)
    assert PostgresRuntimeStore._owner_matches(owner, str(owner))
    assert not PostgresRuntimeStore._owner_matches(str(uuid4()), owner)


def test_source_region_identity_is_shared_by_multiple_evidence_rows():
    first = {"evidence_key": "number-1", "source_region_key": "page-1-span-0"}
    second = {"evidence_key": "text-1", "source_region_key": "page-1-span-0"}

    assert PostgresRuntimeStore._source_region_key(first) == PostgresRuntimeStore._source_region_key(second)
    assert PostgresRuntimeStore._source_region_key({"evidence_key": "fallback"}) == "fallback"
