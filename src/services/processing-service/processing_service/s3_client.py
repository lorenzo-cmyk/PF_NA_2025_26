"""S3-compatible object storage helper using boto3."""

from __future__ import annotations

import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from processing_service.config import Config

log = logging.getLogger(__name__)


class S3Client:
    """Wrapper around boto3 for S3-compatible object storage (RustFS/MinIO)."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._client = boto3.client(
            "s3",
            endpoint_url=cfg.object_storage_url,
            aws_access_key_id=cfg.s3_access_key,
            aws_secret_access_key=cfg.s3_secret_key,
            region_name="us-east-1",
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )
        self._bucket = cfg.s3_bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            log.info("S3 bucket '%s' exists", self._bucket)
        except ClientError:
            log.info("Creating S3 bucket '%s'", self._bucket)
            try:
                self._client.create_bucket(Bucket=self._bucket)
                log.info("S3 bucket '%s' created", self._bucket)
            except ClientError:
                log.exception("Failed to create S3 bucket '%s'", self._bucket)

    def generate_presigned_upload_url(
        self, object_key: str, expires_in: int = 3600
    ) -> str:
        """Generate a presigned PUT URL for uploading an object."""
        url = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )
        log.debug("Presigned upload URL for %s: %s", object_key, url)
        return url

    def generate_presigned_download_url(
        self, object_key: str, expires_in: int = 3600
    ) -> str:
        """Generate a presigned GET URL for downloading an object."""
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )
        return url

    def object_exists(self, object_key: str) -> bool:
        """Check whether an object exists in the bucket."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except ClientError:
            return False

    def get_object(self, object_key: str) -> bytes | None:
        """Download an object and return its bytes, or None if not found."""
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=object_key)
            return resp["Body"].read()
        except ClientError:
            log.warning("Failed to get object %s", object_key)
            return None

    def get_object_url(self, object_key: str) -> str:
        """Return the direct URL of an object (non-presigned)."""
        return f"{self._cfg.object_storage_url}/{self._bucket}/{object_key}"
