from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import build_factorforge_catalog_qa_admission as catalog_qa


_PARQUET_FILE = pq.ParquetFile


class _FakeS3Client:
    def __init__(self, heads: list[dict[str, Any]]) -> None:
        self._heads = heads
        self.calls: list[dict[str, str]] = []

    def head_object(self, **kwargs: str) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        index = min(len(self.calls) - 1, len(self._heads) - 1)
        return deepcopy(self._heads[index])


def _head(*, etag: str = "catalog-etag") -> dict[str, Any]:
    return {
        "ETag": f'"{etag}"',
        "ContentLength": 4096,
        "LastModified": datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc),
        "VersionId": "version-001",
    }


def _invoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    table: pa.Table,
    heads: list[dict[str, Any]] | None = None,
    required_start: str = "2026-01-02",
    required_end: str = "2026-01-05",
    row_group_size: int = 1,
) -> tuple[dict[str, Any], dict[str, Any], _FakeS3Client, Path]:
    parquet_path = tmp_path / "source.parquet"
    pq.write_table(table, parquet_path, row_group_size=row_group_size)
    catalog_path = tmp_path / "catalog.json"
    output_path = tmp_path / "admitted-catalog.json"
    receipt_path = tmp_path / "receipt.json"
    catalog_path.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "dataset_id": "factor_daily",
                        "uri": "s3://factor-bucket/path/factor_daily.parquet",
                        "metadata": {"producer": "fixture"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = _FakeS3Client(heads or [_head(), _head()])
    monkeypatch.setattr(catalog_qa, "_s3_client", lambda _region: client)
    monkeypatch.setattr(catalog_qa.fs, "S3FileSystem", lambda **_kwargs: object())
    monkeypatch.setattr(
        catalog_qa.pq,
        "ParquetFile",
        lambda _path, filesystem: _PARQUET_FILE(parquet_path),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_factorforge_catalog_qa_admission.py",
            "--catalog",
            str(catalog_path),
            "--output-catalog",
            str(output_path),
            "--receipt",
            str(receipt_path),
            "--dataset-id",
            "factor_daily",
            "--required-field",
            "factor_value",
            "--required-start",
            required_start,
            "--required-end",
            required_end,
        ],
    )
    assert catalog_qa.main() == 0
    return (
        json.loads(output_path.read_text(encoding="utf-8")),
        json.loads(receipt_path.read_text(encoding="utf-8")),
        client,
        parquet_path,
    )


def test_catalog_qa_binds_live_object_arrow_schema_and_complete_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = pa.table(
        {
            "trade_date": ["20260102", "20260105"],
            "factor_value": [1.25, 2.5],
        }
    )
    admitted, receipt, client, parquet_path = _invoke(
        tmp_path,
        monkeypatch,
        table=table,
    )

    schema = _PARQUET_FILE(parquet_path).schema_arrow
    expected_schema_sha256 = hashlib.sha256(
        schema.serialize().to_pybytes()
    ).hexdigest()
    assert len(client.calls) == 2
    assert client.calls == [
        {"Bucket": "factor-bucket", "Key": "path/factor_daily.parquet"},
        {"Bucket": "factor-bucket", "Key": "path/factor_daily.parquet"},
    ]
    assert receipt["object_identity"] == {
        "etag": "catalog-etag",
        "content_length": 4096,
        "last_modified_utc": "2026-08-13T08:00:00Z",
        "version_id": "version-001",
    }
    assert receipt["parquet_identity"] == {
        "row_count": 2,
        "row_group_count": 2,
        "schema_encoding": "arrow_ipc_schema_v1",
        "schema_sha256": expected_schema_sha256,
        "trade_date_null_count": 0,
    }
    assert receipt["required_window"] == {
        "start": "2026-01-02",
        "end": "2026-01-05",
    }
    assert receipt["observed_window"] == {
        "start": "2026-01-02",
        "end": "2026-01-05",
    }
    assert receipt["required_field_null_counts"] == {"factor_value": 0}
    unsigned = {
        key: value for key, value in receipt.items() if key != "attestation_sha256"
    }
    assert receipt["attestation_sha256"] == catalog_qa.stable_hash(unsigned)
    admitted_entry = admitted["datasets"][0]
    assert admitted_entry["metadata"]["producer"] == "fixture"
    assert admitted_entry["metadata"]["qa_verdict"] == "ACCEPT"
    assert admitted_entry["metadata"]["host_qa_attestation"] == receipt
    assert admitted_entry["freshness"]["trade_date_min"] == "2026-01-02"
    assert admitted_entry["freshness"]["trade_date_max"] == "2026-01-05"


def test_arrow_schema_hash_changes_when_only_factor_type_changes() -> None:
    numeric = pa.schema(
        [pa.field("trade_date", pa.string()), pa.field("factor_value", pa.float64())]
    )
    textual = pa.schema(
        [pa.field("trade_date", pa.string()), pa.field("factor_value", pa.string())]
    )

    assert numeric.names == textual.names
    assert catalog_qa._canonical_arrow_schema_sha256(
        numeric
    ) != catalog_qa._canonical_arrow_schema_sha256(textual)


@pytest.mark.parametrize("factor_type", [pa.string(), pa.bool_(), pa.list_(pa.int64())])
def test_catalog_qa_rejects_non_numeric_factor_types(factor_type: pa.DataType) -> None:
    schema = pa.schema(
        [pa.field("trade_date", pa.string()), pa.field("factor_value", factor_type)]
    )

    with pytest.raises(SystemExit, match="required factor fields must be numeric"):
        catalog_qa._validate_schema(schema, ["factor_value"])


@pytest.mark.parametrize("trade_date_type", [pa.float64(), pa.bool_(), pa.binary()])
def test_catalog_qa_rejects_unsupported_trade_date_types(
    trade_date_type: pa.DataType,
) -> None:
    schema = pa.schema(
        [
            pa.field("trade_date", trade_date_type),
            pa.field("factor_value", pa.float64()),
        ]
    )

    with pytest.raises(SystemExit, match="unsupported trade_date type"):
        catalog_qa._validate_schema(schema, ["factor_value"])


def test_catalog_qa_rejects_null_factor_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = pa.table(
        {
            "trade_date": ["20260102", "20260105"],
            "factor_value": pa.array([1.0, None], type=pa.float64()),
        }
    )

    with pytest.raises(SystemExit, match="required factor fields contain nulls"):
        _invoke(tmp_path, monkeypatch, table=table)


def test_catalog_qa_rejects_null_trade_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = pa.table(
        {
            "trade_date": pa.array(["20260102", None], type=pa.string()),
            "factor_value": [1.0, 2.0],
        }
    )

    with pytest.raises(SystemExit, match="trade_date contains nulls"):
        _invoke(
            tmp_path,
            monkeypatch,
            table=table,
            required_end="2026-01-02",
            row_group_size=2,
        )


def test_catalog_qa_rejects_uncovered_required_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = pa.table(
        {
            "trade_date": ["20260102", "20260105"],
            "factor_value": [1.0, 2.0],
        }
    )

    with pytest.raises(SystemExit, match="required date coverage"):
        _invoke(
            tmp_path,
            monkeypatch,
            table=table,
            required_start="2026-01-01",
        )


def test_catalog_qa_rejects_object_identity_change_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = pa.table(
        {
            "trade_date": ["20260102", "20260105"],
            "factor_value": [1.0, 2.0],
        }
    )

    with pytest.raises(SystemExit, match="object identity changed"):
        _invoke(
            tmp_path,
            monkeypatch,
            table=table,
            heads=[_head(etag="before"), _head(etag="after")],
        )


def test_catalog_qa_reports_missing_optional_boto3_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = ModuleNotFoundError("No module named 'boto3'", name="boto3")

    def _missing_import(_name: str) -> Any:
        raise missing

    monkeypatch.setattr(catalog_qa.importlib, "import_module", _missing_import)
    with pytest.raises(SystemExit, match=r"install.*\.\[step4\]"):
        catalog_qa._s3_client("ap-southeast-1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20260105", "20260105"),
        ("2026-01-05", "20260105"),
        (20260105, "20260105"),
        (datetime(2026, 1, 5, 12, 0), "20260105"),
    ],
)
def test_catalog_qa_normalizes_supported_date_values(
    value: object,
    expected: str,
) -> None:
    assert catalog_qa._normalize_date(value, label="date") == expected
