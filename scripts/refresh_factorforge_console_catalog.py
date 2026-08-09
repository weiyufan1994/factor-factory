#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.container_agent_adapter import _load_aws_credentials  # noqa: E402
from factor_factory.console.catalog_health import (  # noqa: E402
    CATALOG_BUCKET,
    CATALOG_KEY,
    CATALOG_RECEIPT_VERSION,
)


MAX_CATALOG_BYTES = 32 * 1024 * 1024


def _safe_output(path: str) -> Path:
    output = Path(path).expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if output.is_symlink() or output.parent.is_symlink():
        raise RuntimeError("catalog output path is unsafe")
    return output


def _validate_catalog_payload(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise RuntimeError("active catalog contract is invalid")
    schema_version = payload.get("schema_version")
    datasets = payload.get("datasets")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, (str, int))
        or not str(schema_version).strip()
        or not isinstance(datasets, list)
        or not datasets
        or any(not isinstance(item, dict) or not item.get("dataset_id") for item in datasets)
    ):
        raise RuntimeError("active catalog contract is invalid")
    return datasets


def _fetch_catalog_object(client: object) -> tuple[bytes, dict[str, object]]:
    head = client.head_object(Bucket=CATALOG_BUCKET, Key=CATALOG_KEY)
    head_etag = str(head.get("ETag") or "")
    head_version = str(head.get("VersionId") or "")
    if not head_etag:
        raise RuntimeError("active catalog HEAD response is missing ETag")
    get_request: dict[str, object] = {"Bucket": CATALOG_BUCKET, "Key": CATALOG_KEY}
    if head_version:
        get_request["VersionId"] = head_version
    else:
        get_request["IfMatch"] = head_etag
    response = client.get_object(**get_request)
    response_etag = str(response.get("ETag") or "")
    response_version = str(response.get("VersionId") or "")
    if response_etag != head_etag or (head_version and response_version != head_version):
        raise RuntimeError("active catalog changed between HEAD and GET")
    body = response["Body"]
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = body.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_CATALOG_BYTES:
                raise RuntimeError("active catalog exceeds the Console size limit")
            chunks.append(chunk)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    return b"".join(chunks), dict(head)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the pinned Console Data API catalog read-only.")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument(
        "--role-name",
        default=os.getenv("FACTORFORGE_CONSOLE_AWS_READONLY_ROLE_NAME", ""),
    )
    parser.add_argument(
        "--host-role-name",
        default=os.getenv("FACTORFORGE_CONSOLE_AWS_HOST_ROLE_NAME", ""),
    )
    parser.add_argument(
        "--account-id",
        default=os.getenv("FACTORFORGE_CONSOLE_AWS_ACCOUNT_ID", ""),
    )
    args = parser.parse_args()

    if not args.role_name or not args.host_role_name or not re.fullmatch(r"[0-9]{12}", args.account_id):
        raise RuntimeError("pinned Console account, host role, and read-only role are required")
    credentials = _load_aws_credentials(
        args.role_name,
        args.host_role_name,
        args.account_id,
    )
    import botocore.session

    client = botocore.session.get_session().create_client(
        "s3",
        region_name="ap-southeast-1",
        aws_access_key_id=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        aws_session_token=credentials.token,
    )
    data, head = _fetch_catalog_object(client)
    head_etag = str(head.get("ETag") or "")
    head_version = str(head.get("VersionId") or "")
    payload = json.loads(data)
    datasets = _validate_catalog_payload(payload)

    destination = _safe_output(args.destination)
    receipt_path = _safe_output(args.receipt)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    temporary.replace(destination)
    destination.chmod(0o640)

    last_modified = head.get("LastModified")
    receipt = {
        "version": CATALOG_RECEIPT_VERSION,
        "bucket": CATALOG_BUCKET,
        "key": CATALOG_KEY,
        "etag": head_etag.strip('"'),
        "version_id": head_version,
        "source_last_modified_utc": (
            last_modified.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if isinstance(last_modified, datetime)
            else ""
        ),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "catalog_sha256": hashlib.sha256(data).hexdigest(),
        "catalog_bytes": len(data),
        "dataset_count": len(datasets),
        "schema_version": payload["schema_version"],
        "role_name": args.role_name,
    }
    receipt_temp = receipt_path.with_name(f".{receipt_path.name}.{os.getpid()}.tmp")
    receipt_temp.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_temp.chmod(0o640)
    receipt_temp.replace(receipt_path)
    print(json.dumps({"status": "PASS", "dataset_count": len(datasets)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
