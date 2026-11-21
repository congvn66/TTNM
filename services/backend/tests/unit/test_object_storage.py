from __future__ import annotations

import pytest

from report_qa.infrastructure.object_storage import LocalObjectStorage, ObjectStorageError, validate_object_key


@pytest.mark.parametrize("key", ["documents/abc.pdf", "extractions/abc.json", "owners/a/versions/b.pdf"])
def test_server_owned_object_key_is_relative_posix(key: str) -> None:
    assert validate_object_key(key) == key


@pytest.mark.parametrize("key", ["", "../secret.pdf", "/absolute.pdf", "documents\\escape.pdf"])
def test_object_key_rejects_path_traversal(key: str) -> None:
    with pytest.raises(ObjectStorageError):
        validate_object_key(key)


def test_local_storage_is_explicit_offline_adapter() -> None:
    assert LocalObjectStorage().health() == {
        "backend": "local",
        "configured": True,
        "durability": "local_disk",
        "status": "ok",
    }
