from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..registry.report_source_contract import ReportSource, normalize_report_source


class S3PdfAdapter:
    def __init__(
        self,
        bucket: str,
        prefix: str,
        cache_root: str | Path,
        s3_client: Any,
    ):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.s3_client = s3_client

    def list_pdf_keys(self) -> List[str]:
        paginator = self.s3_client.get_paginator("list_objects_v2")
        keys: List[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if key.lower().endswith(".pdf"):
                    keys.append(key)
        return keys

    def build_source_from_key(self, s3_key: str) -> ReportSource:
        title = self.infer_title_from_key(s3_key)
        broker = self.infer_broker_from_key(s3_key)
        metadata = self.fetch_metadata(s3_key)
        return normalize_report_source(
            source_type="pdf",
            source_uri=f"s3://{self.bucket}/{s3_key}",
            title=title,
            broker=broker,
            metadata=metadata,
        )

    def fetch_metadata(self, s3_key: str) -> Dict[str, Any]:
        head = self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
        return {
            "bucket": self.bucket,
            "key": s3_key,
            "etag": head.get("ETag"),
            "content_length": head.get("ContentLength"),
            "last_modified": str(head.get("LastModified")),
        }

    def cache_pdf(self, source: ReportSource) -> ReportSource:
        local_dir = self.cache_root / source.report_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / "source.pdf"
        key = source.metadata.get("key") or source.source_uri.replace(f"s3://{self.bucket}/", "")
        self.s3_client.download_file(self.bucket, key, str(local_path))
        source.local_cache_path = str(local_path)
        source.status = "cached"
        return source

    def infer_title_from_key(self, s3_key: str) -> str:
        return Path(s3_key).stem

    def infer_broker_from_key(self, s3_key: str) -> Optional[str]:
        parts = Path(s3_key).parts
        return parts[-2] if len(parts) >= 2 else None
