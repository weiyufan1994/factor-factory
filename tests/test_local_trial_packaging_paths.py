from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_factorforge_local_trial as builder


def test_trial_explicitly_packages_public_pfvv_sources_without_private_data():
    paths = list(builder.PATCH_PATHS)
    assert len(paths) == len(set(paths))
    required = {
        "examples/mszq_intraday_momentum_pulse/pfvv_monthly_step4_backend_v1.py",
        "examples/mszq_intraday_momentum_pulse/pfvv_daily_lookup_store_v1.py",
        "examples/mszq_intraday_momentum_pulse/pfvv_prepared_inputs_v1.py",
        "examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py",
        "examples/mszq_intraday_momentum_pulse/pfvv_market_inputs_v1.py",
        "scripts/package_pfvv_prepared_outputs.py",
        "tests/test_mszq_pfvv_monthly_step4_backend_v1.py",
        "tests/test_mszq_pfvv_daily_lookup_store_v1.py",
        "tests/test_mszq_pfvv_prepared_inputs_v1.py",
        "tests/test_mszq_pfvv_daily_measurements_v1.py",
        "tests/test_mszq_pfvv_market_inputs_v1.py",
        "tests/test_package_pfvv_prepared_outputs.py",
        "tests/test_factorforge_measurement_program_pipeline.py",
        "tests/test_step6_researcher_identity.py",
        "tests/test_main_agent_memo_step2_knowledge_projection.py",
        "tests/test_main_agent_memo_v1_direct_code_projection.py",
        "tests/test_pfvv_trade_ledger_encoding.py",
        "tests/test_pfvv_step4_pipeline_integration.py",
        "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/mszq_step4_portfolio_evaluator_candidate_v1.py",
        "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/mszq_evaluation_calendar_candidate_v1.py",
        "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/mszq_v17_normalized_constraints_candidate_v1.py",
        "examples/mszq_intraday_momentum_pulse/local_is_execution_engine/README.zh-CN.md",
    }
    assert required <= set(paths)
    assert not any("factor_research/" in path or path.endswith(".parquet") for path in paths)
    assert all((Path(builder.REPO) / path).is_file() for path in required)
    assert len(set(builder.STANDALONE)) == len(builder.STANDALONE)
    assert "tests/test_local_trial_packaging_paths.py" not in builder.STANDALONE
    assert "tests/test_pfvv_trade_ledger_encoding.py" in builder.STANDALONE
    assert "tests/test_pfvv_step4_pipeline_integration.py" not in builder.STANDALONE
    assert "tests/test_mszq_pfvv_prepared_inputs_v1.py" not in builder.STANDALONE
    assert "tests/test_mszq_pfvv_source_baseline_partitioned_v1.py" not in builder.STANDALONE
    assert "tests/test_mszq_pfvv_daily_measurements_v1.py" not in builder.STANDALONE
    assert "factor_factory/partitioned_direct_code.py" in builder.STANDALONE
    assert "factor_factory/primary_evaluator.py" in builder.STANDALONE
    assert "factor_factory/__init__.py" in builder.STANDALONE
    assert "numpy>=1.24" in "numpy>=1.24\npandas>=2.1\npyarrow>=14.0\npsutil>=5.9\npytest>=7.0\n"
    assert "pyarrow>=14.0" in "numpy>=1.24\npandas>=2.1\npyarrow>=14.0\npsutil>=5.9\npytest>=7.0\n"
    assert "psutil>=5.9" in "numpy>=1.24\npandas>=2.1\npyarrow>=14.0\npsutil>=5.9\npytest>=7.0\n"
