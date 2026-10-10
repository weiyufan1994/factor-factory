"""Full-source compatibility only; the research distribution omits hosted code."""
from tests.test_common_research_services import _calendar
from factor_factory.data_access import calendar_snapshot as snapshot
from factor_factory.evaluation_contract import build_web_evaluation_contract, stable_json_hash


def test_console_keeps_the_same_pure_evaluation_exports():
    from factor_factory.console import web_research_plan as old
    assert old.build_web_evaluation_contract is build_web_evaluation_contract
    assert old.stable_json_hash is stable_json_hash


def test_old_console_entry_uses_new_calendar_service(tmp_path, monkeypatch):
    from factor_factory.console import web_factor_proof as web
    path, _, options = _calendar(tmp_path)
    monkeypatch.setenv("FACTORFORGE_TRUSTED_TRADE_CAL_CSV", str(path))
    for name, key in [
        ("TRADING_CALENDAR_REGISTRY_PATH", "registry_path"),
        ("TRADING_CALENDAR_REGISTRY_TRUST_SHA256", "registry_sha256"),
        ("TRADING_CALENDAR_REGISTRY_TRUST_COMMIT", "registry_git_commit"),
        ("TRADING_CALENDAR_REGISTRY_TRUST_BLOB", "registry_git_blob"),
        ("CALENDAR_SNAPSHOT_ID", "snapshot_id"),
    ]:
        monkeypatch.setattr(snapshot, name, options[key])
    assert web._trusted_calendar_snapshot(workspace_root=options["workspace_root"]) == snapshot.read_calendar_snapshot(path, **options)
    assert web.validate_trusted_calendar_snapshot is snapshot.validate_trusted_calendar_snapshot


def test_hosted_compatibility_signatures_and_arguments(monkeypatch):
    import inspect
    from factor_factory import evo_memory_retrieval as hosted, knowledge_context as generic
    names = (
        "validate_evo_v2_cold_start_search_receipt", "prepare_evo_v2_cold_start_search_session",
        "build_evo_v2_cold_start_search_prompt", "complete_evo_v2_cold_start_search_session",
        "retrieve_evo_v2_memory_projection",
    )
    for name in names:
        wrapper, implementation = getattr(generic, name), getattr(hosted, name)
        assert inspect.signature(wrapper) == inspect.signature(implementation)
        positional, kwargs = [], {}
        for parameter in inspect.signature(wrapper).parameters.values():
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs[parameter.name] = object()
            else:
                positional.append(object())
        observed = []
        def probe(*args, **kw):
            observed.append((args, kw))
            return "forwarded"
        with monkeypatch.context() as patch:
            patch.setattr(hosted, name, probe)
            assert wrapper(*positional, **kwargs) == "forwarded"
        assert observed == [(tuple(positional), kwargs)]
