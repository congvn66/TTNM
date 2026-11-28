"""Object-storage adapters for immutable PDF and extraction artifacts.

Cloudflare R2 exposes an S3-compatible API. The local adapter remains only
for offline tests and as a disk cache; selecting ``STORAGE_BACKEND=r2`` never
falls back silently when credentials or the bucket are unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from report_qa.config import Settings


class ObjectStorageError(RuntimeError):
    """Stable storage failure that is safe to expose operationally."""


def validate_object_key(key: str) -> str:
    """Accept only relative, server-owned POSIX object keys."""
    candidate = PurePosixPath(key)
    if not key or candidate.is_absolute() or ".." in candidate.parts or "\\" in key:
        raise ObjectStorageError("invalid object storage key")
    return candidate.as_posix()


class ObjectStorage(Protocol):
    backend: str

    def upload_file(self, key: str, source: Path, *, content_type: str) -> None: ...
    def download_file(self, key: str, destination: Path) -> None: ...
    def delete_file(self, key: str) -> None: ...
    def health(self) -> dict[str, object]: ...


@dataclass(slots=True)
class LocalObjectStorage:
    """Deliberate offline adapter; application owns the local paths/cache."""

    backend: str = "local"

    def upload_file(self, key: str, source: Path, *, content_type: str) -> None:
        del key, source, content_type

    def download_file(self, key: str, destination: Path) -> None:
        del key, destination

    def delete_file(self, key: str) -> None:
        del key  # local files belong to the application's runtime folder

    def health(self) -> dict[str, object]:
        return {"backend": self.backend, "configured": True, "status": "ok", "durability": "local_disk"}


class CloudflareR2ObjectStorage:
    backend = "r2"

    def __init__(self, *, endpoint: str, bucket: str, access_key_id: str, secret_access_key: str, region: str = "auto") -> None:
        values = {
            "R2_ENDPOINT": endpoint,
            "R2_BUCKET": bucket,
            "R2_ACCESS_KEY_ID": access_key_id,
            "R2_SECRET_ACCESS_KEY": secret_access_key,
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ObjectStorageError(f"missing Cloudflare R2 configuration: {', '.join(missing)}")
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ObjectStorageError("Cloudflare R2 requires the object-storage dependency; install .[object-storage]") from exc
        self.bucket = bucket
        self._client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )

    def upload_file(self, key: str, source: Path, *, content_type: str) -> None:
        key = validate_object_key(key)
        if not source.is_file():
            raise ObjectStorageError("source file is missing before R2 upload")
        try:
            self._client.upload_file(str(source), self.bucket, key, ExtraArgs={"ContentType": content_type})
        except Exception as exc:
            raise ObjectStorageError("Cloudflare R2 upload failed") from exc

    def download_file(self, key: str, destination: Path) -> None:
        key = validate_object_key(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".downloading")
        try:
            self._client.download_file(self.bucket, key, str(temporary))
            temporary.replace(destination)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise ObjectStorageError("Cloudflare R2 download failed") from exc

    def delete_file(self, key: str) -> None:
        key = validate_object_key(key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)  # no error when the key is already gone
        except Exception as exc:
            raise ObjectStorageError("Cloudflare R2 delete failed") from exc

    def health(self) -> dict[str, object]:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception:
            return {"backend": self.backend, "configured": True, "status": "unavailable", "bucket": self.bucket}
        return {"backend": self.backend, "configured": True, "status": "ok", "bucket": self.bucket, "durability": "cloudflare_r2"}


def build_object_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "local":
        return LocalObjectStorage()
    return CloudflareR2ObjectStorage(
        endpoint=settings.r2_endpoint,
        bucket=settings.r2_bucket,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        region=settings.r2_region,
    )


__all__ = ["CloudflareR2ObjectStorage", "LocalObjectStorage", "ObjectStorage", "ObjectStorageError", "build_object_storage", "validate_object_key"]
