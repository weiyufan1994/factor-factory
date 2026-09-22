from pathlib import Path


def test_verified_main_agent_validator_never_imports_mutable_host_modules(
    tmp_path,
    monkeypatch,
):
    import sys

    import factor_factory.artifact_identity as mutable_artifact_identity
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    config = ConsoleConfig(
        source_repo=tmp_path,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        config,
        trusted_engine_commit="a" * 40,
    )
    sources = {
        Path("factor_factory/artifact_identity.py"): b"""
def stable_hash(_value):
    return "VERIFIED_ENGINE_BLOB"
""",
        Path("factor_factory/formula/field_aliases.py"): b"",
        Path("factor_factory/formula/ir.py"): b"",
        Path("factor_factory/formula/registry.py"): b"""
def operator_meta(_name):
    return {"source": "VERIFIED_ENGINE_BLOB"}
""",
        Path("factor_factory/formula/semantics.py"): b"",
        Path("factor_factory/formula/parser.py"): b"""
from factor_factory.artifact_identity import stable_hash

def parse_formula(value):
    return stable_hash(value)
""",
        Path("factor_factory/knowledge_reference.py"): b"""
def validate_knowledge_reference_contract(_value):
    return ["VERIFIED_ENGINE_BLOB"]
""",
        Path("factor_factory/measurement_program.py"): b"""
def validate_measurement_program(_value):
    return ["VERIFIED_ENGINE_BLOB"]
""",
        Path("factor_factory/mechanism_math/formula_specific.py"): b"""
BASELINE_MODEL_FAMILIES = {"verified"}

def build_formula_understanding(_value):
    return "VERIFIED_ENGINE_BLOB"
""",
        Path("factor_factory/mechanism_math/main_agent_memo.py"): b"""
from ..formula.parser import parse_formula
from ..formula.registry import operator_meta
from ..knowledge_reference import validate_knowledge_reference_contract
from ..measurement_program import validate_measurement_program
from .formula_specific import BASELINE_MODEL_FAMILIES, build_formula_understanding

def validate_main_agent_mechanism_memo(memo, context):
    return [
        parse_formula(memo),
        operator_meta("verified")["source"],
        validate_knowledge_reference_contract(context)[0],
        validate_measurement_program(context)[0],
        build_formula_understanding(BASELINE_MODEL_FAMILIES),
    ]
""",
    }
    observed_relatives = []

    def read_verified_engine_blob(*, relative, **_kwargs):
        observed_relatives.append(relative)
        return sources[relative]

    monkeypatch.setattr(
        adapter,
        "_read_verified_engine_blob",
        read_verified_engine_blob,
    )
    monkeypatch.setattr(
        mutable_artifact_identity,
        "stable_hash",
        lambda _value: "MUTABLE_HOST",
    )

    validator = adapter._load_verified_main_agent_validator(
        engine_root=tmp_path,
        git_dir=tmp_path / ".git",
        engine_commit="a" * 40,
    )

    assert observed_relatives == list(sources)
    assert validator({}, {}) == ["VERIFIED_ENGINE_BLOB"] * 5
    verified_parse_formula = validator.__globals__["parse_formula"]
    assert (
        verified_parse_formula.__globals__["stable_hash"]
        is not mutable_artifact_identity.stable_hash
    )
    trusted_prefix = validator.__module__.split(".factor_factory", 1)[0]
    assert trusted_prefix.startswith("_factorforge_trusted_engine_")
    assert not any(
        name == trusted_prefix or name.startswith(f"{trusted_prefix}.")
        for name in sys.modules
    )


def test_verified_council_validator_never_imports_mutable_host_modules(
    tmp_path,
    monkeypatch,
):
    import sys

    import factor_factory.revision_council.evo_v2 as mutable_council_evo
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
    )

    config = ConsoleConfig(
        source_repo=tmp_path,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(
        config,
        trusted_engine_commit="a" * 40,
    )
    source_paths = (
        "factor_factory/research_workspace.py",
        "factor_factory/research_org/contracts.py",
        "factor_factory/research_org/runtime_trust.py",
        "factor_factory/human_approval.py",
        "factor_factory/oos_exposure_incident.py",
        "factor_factory/evo_oos.py",
        "factor_factory/research_evidence.py",
        "factor_factory/research_release.py",
        "factor_factory/metric_verifier.py",
        "factor_factory/research_proof.py",
        "factor_factory/research_obligation_verifier.py",
        "factor_factory/evo_v2.py",
        "factor_factory/measurement_program.py",
        "factor_factory/research_conjecture.py",
        "factor_factory/revision_council/evo_v2.py",
        "factor_factory/revision_council/production.py",
        "skills/factor-forge-step6/scripts/validate_agentic_council_result.py",
    )
    sources = {Path(relative): b"" for relative in source_paths}
    sources[Path("factor_factory/revision_council/evo_v2.py")] = b"""
BLOCK_MISSING = "VERIFIED_BLOCK"

def validate_council_evo_v2_intake(*_args, **_kwargs):
    return ["VERIFIED_ENGINE_BLOB"]
"""
    sources[Path("factor_factory/revision_council/production.py")] = b"""
class CouncilEvoProductionError(Exception):
    def __init__(self, reasons=()):
        self.reasons = list(reasons)

def load_formal_evo_packet_context(*_args, **_kwargs):
    return None, None

def validate_result_evo_identity(*_args, **_kwargs):
    return []
"""
    sources[
        Path(
            "skills/factor-forge-step6/scripts/"
            "validate_agentic_council_result.py"
        )
    ] = b"""
from factor_factory.revision_council.evo_v2 import validate_council_evo_v2_intake

def validate_agentic_result(*_args, **_kwargs):
    return validate_council_evo_v2_intake({})
"""
    observed_relatives = []

    def read_verified_engine_blob(*, relative, **_kwargs):
        observed_relatives.append(relative)
        return sources[relative]

    monkeypatch.setattr(
        adapter,
        "_read_verified_engine_blob",
        read_verified_engine_blob,
    )
    monkeypatch.setattr(
        mutable_council_evo,
        "validate_council_evo_v2_intake",
        lambda *_args, **_kwargs: ["MUTABLE_HOST"],
    )

    validator = adapter._load_verified_council_validator(
        engine_root=tmp_path,
        git_dir=tmp_path / ".git",
        engine_commit="a" * 40,
        workspace=tmp_path / "workspace",
    )

    assert observed_relatives == list(sources)
    assert validator({}) == ["VERIFIED_ENGINE_BLOB"]
    verified_validate = validator.__globals__["validate_council_evo_v2_intake"]
    assert verified_validate is not mutable_council_evo.validate_council_evo_v2_intake
    trusted_prefix = validator.__module__.split(".factor_factory", 1)[0]
    assert trusted_prefix.startswith("_factorforge_trusted_council_")
    assert not any(
        name == trusted_prefix or name.startswith(f"{trusted_prefix}.")
        for name in sys.modules
    )
