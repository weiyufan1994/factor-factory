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
