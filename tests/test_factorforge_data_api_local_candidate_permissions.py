from pathlib import Path


def test_clean_daily_inaccessible_local_candidate_falls_through_to_catalog(
    tmp_path,
    monkeypatch,
):
    import factor_factory.data_api.client as client

    inaccessible = Path(
        "/home/ubuntu/projects/factor-factory-data-api/data/clean/daily_clean.parquet"
    )
    absent_candidates = {
        Path(
            "/Users/humphrey/projects/factor-factory-data-api/data/clean/daily_clean.parquet"
        ),
    }
    original_exists = Path.exists

    def guarded_exists(path):
        if path == inaccessible:
            raise PermissionError("legacy warm cache is outside the service boundary")
        if path in absent_candidates:
            return False
        return original_exists(path)

    expected = object()
    observed = {}

    class FakeClient:
        def fetch(self, query):
            observed["query"] = query
            return expected

    def fake_from_catalog(catalog):
        observed["catalog"] = catalog
        return FakeClient()

    catalog = tmp_path / "data_catalog.json"
    monkeypatch.delenv("FACTORFORGE_CLEAN_DAILY_PARQUET", raising=False)
    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(client.IndependentDataApiClient, "from_catalog", fake_from_catalog)

    result = client.fetch_data_api_dataset(
        "clean_daily_bar",
        start="20200102",
        end="20200103",
        fields=["open", "close"],
        catalog_path=catalog,
    )

    assert result is expected
    assert observed["catalog"] == catalog
    assert observed["query"].dataset == "clean_daily_bar"
    assert observed["query"].fields == ["open", "close"]


def test_catalog_fetch_hardens_and_restores_pyarrow_s3_transport(tmp_path, monkeypatch):
    import pyarrow.fs as arrow_fs

    import factor_factory.data_api.client as client

    observed = {}

    def original_s3(*args, **kwargs):
        observed["kwargs"] = kwargs
        return object()

    class FakeClient:
        def fetch(self, query):
            arrow_fs.S3FileSystem(region="ap-southeast-1")
            return query

    monkeypatch.setattr(arrow_fs, "S3FileSystem", original_s3)
    monkeypatch.setattr(
        client.IndependentDataApiClient,
        "from_catalog",
        lambda catalog: FakeClient(),
    )
    monkeypatch.setenv("FACTORFORGE_DISABLE_CLEAN_DAILY_LOCAL_PARQUET", "1")
    monkeypatch.setenv("FACTORFORGE_S3_REQUEST_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("FACTORFORGE_S3_CONNECT_TIMEOUT_SECONDS", "45")
    catalog = tmp_path / "data_catalog.json"

    client.fetch_data_api_dataset(
        "clean_daily_bar",
        start="20200102",
        end="20200103",
        fields=["close"],
        catalog_path=catalog,
    )

    assert observed["kwargs"]["request_timeout"] == 180.0
    assert observed["kwargs"]["connect_timeout"] == 45.0
    assert observed["kwargs"]["retry_strategy"] is not None
    assert arrow_fs.S3FileSystem is original_s3
