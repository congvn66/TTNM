from uuid import uuid4

from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore


def test_catalog_owner_match_accepts_json_string_and_uuid_forms():
    owner = uuid4()

    assert PostgresRuntimeStore._owner_matches(str(owner), owner)
    assert PostgresRuntimeStore._owner_matches(owner, str(owner))
    assert not PostgresRuntimeStore._owner_matches(str(uuid4()), owner)
