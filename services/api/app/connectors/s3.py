from __future__ import annotations

import boto3

from app.connectors.base import ObjectMeta


class S3Connector:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        region_name: str,
    ) -> None:
        self._bucket = bucket_name
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
        )

    def list_prefixes(self, prefix: str) -> list[str]:
        resp = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix, Delimiter="/")
        return [p["Prefix"] for p in resp.get("CommonPrefixes", [])]

    def list_objects(self, prefix: str) -> list[ObjectMeta]:
        objects: list[ObjectMeta] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                objects.append(
                    ObjectMeta(
                        key=obj["Key"],
                        etag=obj["ETag"].strip('"'),
                        size=obj["Size"],
                        last_modified=obj["LastModified"],
                    )
                )
        return objects

    def get_object_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()
