"""S3 contract verified against the installed botocore S3 service model.

Conditional PutObject/CompleteMultipartUpload prevent replacement. Checksums are full
read-back SHA-256, never multipart ETags or untrusted object metadata.
"""

import hashlib
from collections.abc import Iterator
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, SSLError
from mypy_boto3_s3 import S3Client
from mypy_boto3_s3.type_defs import CompletedPartTypeDef

from ontology_platform.artifacts.config import StorageSettings
from ontology_platform.artifacts.storage import Failure, ObjectInfo, ObjectKey, StorageError


def translate(exc: BotoCoreError | ClientError) -> StorageError:
    if isinstance(exc, (NoCredentialsError, SSLError)):
        return StorageError(Failure.CONFIGURATION)
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "NotFound", "404"}:
            return StorageError(Failure.MISSING)
        if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "403"}:
            return StorageError(Failure.ACCESS)
        if code in {"PreconditionFailed", "ConditionalRequestConflict", "412"}:
            return StorageError(Failure.EXISTS)
        if code in {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "503"}:
            return StorageError(Failure.TRANSIENT)
        return StorageError(Failure.PERMANENT)
    return StorageError(Failure.TRANSIENT)


class S3ArtifactStore:
    backend = "s3"

    def __init__(self, settings: StorageSettings, client: S3Client | None = None):
        self.settings = settings
        self.client: S3Client = client or boto3.client(
            "s3",
            endpoint_url=settings.endpoint,
            region_name=settings.region,
            aws_access_key_id=settings.access_key.get_secret_value()
            if settings.access_key
            else None,
            aws_secret_access_key=settings.secret_key.get_secret_value()
            if settings.secret_key
            else None,
            verify=str(settings.ca_bundle) if settings.ca_bundle else True,
            config=Config(
                connect_timeout=settings.connect_seconds,
                read_timeout=settings.read_seconds,
                retries={"total_max_attempts": settings.attempts, "mode": "standard"},
                s3={"addressing_style": settings.addressing},
            ),
        )

    def put(self, key: ObjectKey, source: BinaryIO, size: int, checksum: str) -> None:
        if not 0 <= size <= self.settings.max_bytes:
            raise StorageError(Failure.INTEGRITY)
        upload: str | None = None
        try:
            if size <= self.settings.part_bytes:
                self.client.put_object(
                    Bucket=self.settings.bucket,
                    Key=str(key),
                    Body=source,
                    ContentLength=size,
                    ContentType="application/octet-stream",
                    IfNoneMatch="*",
                )
            else:
                upload = self.client.create_multipart_upload(
                    Bucket=self.settings.bucket,
                    Key=str(key),
                    ContentType="application/octet-stream",
                )["UploadId"]
                parts: list[CompletedPartTypeDef] = []
                remaining = size
                while remaining:
                    data = source.read(min(remaining, self.settings.part_bytes))
                    if not data:
                        raise StorageError(Failure.INTEGRITY)
                    part = self.client.upload_part(
                        Bucket=self.settings.bucket,
                        Key=str(key),
                        UploadId=upload,
                        PartNumber=len(parts) + 1,
                        Body=data,
                    )
                    parts.append({"ETag": part["ETag"], "PartNumber": len(parts) + 1})
                    remaining -= len(data)
                self.client.complete_multipart_upload(
                    Bucket=self.settings.bucket,
                    Key=str(key),
                    UploadId=upload,
                    MultipartUpload={"Parts": parts},
                    IfNoneMatch="*",
                )
                upload = None
        except (BotoCoreError, ClientError) as exc:
            raise translate(exc) from exc
        finally:
            if upload:
                self.abort_pending(key)
        self.verify(key, size, checksum)

    def chunks(self, key: ObjectKey) -> Iterator[bytes]:
        try:
            response = self.client.get_object(Bucket=self.settings.bucket, Key=str(key))
            body = response["Body"]
            try:
                yield from body.iter_chunks(chunk_size=65536)
            finally:
                body.close()
        except (BotoCoreError, ClientError) as exc:
            raise translate(exc) from exc

    def head(self, key: ObjectKey) -> ObjectInfo:
        try:
            result = self.client.head_object(Bucket=self.settings.bucket, Key=str(key))
            return ObjectInfo(result["ContentLength"])
        except (BotoCoreError, ClientError) as exc:
            raise translate(exc) from exc

    def exists(self, key: ObjectKey) -> bool:
        try:
            self.head(key)
            return True
        except StorageError as exc:
            if exc.category != Failure.MISSING:
                raise
            return False

    def verify(self, key: ObjectKey, size: int, checksum: str) -> ObjectInfo:
        if self.head(key).size != size or size > self.settings.max_bytes:
            raise StorageError(Failure.INTEGRITY)
        digest, count = hashlib.sha256(), 0
        for chunk in self.chunks(key):
            count += len(chunk)
            if count > size:
                raise StorageError(Failure.INTEGRITY)
            digest.update(chunk)
        if count != size or digest.hexdigest() != checksum:
            raise StorageError(Failure.INTEGRITY)
        return ObjectInfo(size, checksum)

    def delete(self, key: ObjectKey) -> None:
        try:
            self.client.delete_object(Bucket=self.settings.bucket, Key=str(key))
        except (BotoCoreError, ClientError) as exc:
            raise translate(exc) from exc

    def presign(self, key: ObjectKey) -> str:
        if not self.settings.client_reachable:
            raise StorageError(Failure.CONFIGURATION)
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.settings.bucket,
                    "Key": str(key),
                    "ResponseContentDisposition": "attachment",
                    "ResponseContentType": "application/octet-stream",
                },
                ExpiresIn=self.settings.presign_seconds,
                HttpMethod="GET",
            )
        except (BotoCoreError, ClientError) as exc:
            raise translate(exc) from exc

    def abort_pending(self, key: ObjectKey) -> None:
        try:
            # Exact key matching, bounded page iteration; no object-prefix deletion.
            pager = self.client.get_paginator("list_multipart_uploads")
            for page in pager.paginate(Bucket=self.settings.bucket, Prefix=str(key)):
                for upload in page.get("Uploads", []):
                    if upload["Key"] == str(key):
                        self.client.abort_multipart_upload(
                            Bucket=self.settings.bucket, Key=str(key), UploadId=upload["UploadId"]
                        )
        except (BotoCoreError, ClientError) as exc:
            raise translate(exc) from exc
