"""Frozen e07e5781 Step4 main for refactor parity, synthetic tests only."""
def main() -> None:
    global FACTORFORGE, WORKSPACE, OBJ, RUNS, _RUNTIME_MANIFEST
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    ap.add_argument('--enable-shared-evaluation-context', action='store_true')
    ap.add_argument(
        '--trusted-data-prefetch-only',
        action='store_true',
        help='Host-only EVO IS fetch/materialization; never imports factor code.',
    )
    ap.add_argument(
        '--expected-host-trust-manifest-sha256',
        default=None,
        help=(
            'Externally pinned Host public trust-manifest digest required for '
            'formal EVO child diagnostic execution.'
        ),
    )
    args = ap.parse_args()
    enforce_direct_step_policy(args.manifest)
    manifest: dict[str, Any] | None = load_runtime_manifest(args.manifest) if args.manifest else None
    _RUNTIME_MANIFEST = manifest
    if manifest:
        FACTORFORGE = manifest_factorforge_root(manifest)
        WORKSPACE = FACTORFORGE.parent
        OBJ = FACTORFORGE / 'objects'
        RUNS = FACTORFORGE / 'runs'
    report_id = args.report_id or (manifest_report_id(manifest) if manifest else None)
    if not report_id:
        raise SystemExit('run_step4.py requires --report-id or --manifest')
    manifest_path_arg = Path(args.manifest).expanduser() if args.manifest else None
    start_utc = utc_now()
    input_paths = resolve_input_paths(report_id, manifest=manifest)
    run_dir = RUNS / report_id
    ensure_dir(run_dir)
    state_resolution_raw = (
        os.getenv('FACTORFORGE_STATE_RESOLUTION')
        or ((manifest.get('state_reuse') or {}).get('state_resolution') if manifest else None)
    )
    state_resolution_path = Path(state_resolution_raw).expanduser() if state_resolution_raw else None
    state_reuse_required = os.getenv('FACTORFORGE_REQUIRE_STATE_REUSE_CONTRACT') == '1'
    state_datamart_reuse: dict[str, Any] | None = None

    issues: list[dict[str, Any]] = []
    warnings: list[str] = []
    fsm: dict[str, Any] = {}
    dpm: dict[str, Any] = {}
    handoff: dict[str, Any] = {}
    factor_id: str | None = None
    implementation_path: str | None = None

    try:
        missing = [name for name, path in input_paths.items() if not path.exists()]
        if missing:
            for name in missing:
                issues.append({'severity': 'error', 'code': 'MISSING_INPUT', 'message': f'missing required input: {name}', 'evidence': {'path': str(input_paths[name])}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, None, None, {}, run_dir, input_paths, issues, warnings, 'MISSING_REQUIRED_INPUT', 'input_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        fsm = load_json(input_paths['factor_spec_master'])
        validate_web_evaluation_contract(fsm)
        dpm = load_json(input_paths['data_prep_master'])
        handoff = load_json(input_paths['handoff_to_step4'])
        # Parse an explicit study-local primary declaration before any large
        # parent frame is materialized.  This only selects an IO shape; it is
        # not evidence that the caller or backend is independently certified.
        evaluation_plan = build_evaluation_plan(handoff)
        try:
            custom_primary = primary_evaluator_plan(evaluation_plan)
        except ValueError as exc:
            raise ValueError(f'BLOCK_PRIMARY_EVALUATOR_PLAN_INVALID:{exc}') from exc
        if custom_primary is not None and os.getenv('FACTORFORGE_LOCAL_IS_ONLY') != '1':
            raise ValueError('BLOCK_PRIMARY_EVALUATOR_LOCAL_IS_ONLY')
        apply_evo_pre_release_data_boundary(
            report_id,
            dpm,
            handoff,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
        )
        if args.trusted_data_prefetch_only:
            if not isinstance(dpm.get('research_windows'), dict):
                raise SystemExit(
                    'BLOCK_FACTORFORGE_EVO_PRE_RELEASE_DATA_RECEIPT_INVALID: not_evo'
                )
            receipt = materialize_evo_pre_release_data_receipt(
                report_id=report_id,
                dpm=dpm,
                handoff=handoff,
                run_dir=run_dir,
            )
            print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
            return
        if state_resolution_path and state_resolution_path.exists():
            try:
                state_datamart_reuse = build_step4_state_reuse_provenance(
                    state_resolution_path=state_resolution_path,
                    bounded_smoke=False,
                    raw_minute_full_window_scan=False,
                )
            except StateReuseBlock as exc:
                raise SystemExit(str(exc)) from exc
        elif state_reuse_required:
            raise SystemExit(
                f'{BLOCK_STATE_RESOLUTION_MISSING}: {state_resolution_path}'
            )
        evo_diagnostic_contract = fsm.get('evo_transfer_diagnostic_contract')
        handoff_evo_contract = handoff.get('evo_transfer_diagnostic_contract')
        if evo_diagnostic_contract is not None or handoff_evo_contract is not None:
            if not isinstance(evo_diagnostic_contract, dict) or handoff_evo_contract != evo_diagnostic_contract:
                raise ValueError('BLOCK_FACTORFORGE_EVO_CHILD_DIAGNOSTIC_CONTRACT_PROJECTION')
            parent_report_id = str(evo_diagnostic_contract.get('parent_report_id') or '')
            if not args.expected_host_trust_manifest_sha256:
                raise ValueError('BLOCK_FACTORFORGE_EVO_CHILD_EXTERNAL_HOST_TRUST_PIN_REQUIRED')
            diagnostic_reasons = validate_evo_transfer_diagnostic_contract(
                evo_diagnostic_contract,
                workspace_root=FACTORFORGE,
                parent_report_id=parent_report_id,
                child_report_id=report_id,
                expected_host_trust_manifest_sha256=(
                    args.expected_host_trust_manifest_sha256
                ),
            )
            if diagnostic_reasons:
                raise ValueError(';'.join(diagnostic_reasons))
        else:
            evo_diagnostic_contract = None
        base_identity = handoff.get('artifact_identity') or fsm.get('artifact_identity') or {}
        implementation_mode_decision = (
            handoff.get('implementation_mode_decision')
            or fsm.get('implementation_mode_decision')
            or {}
        )
        factor_id = fsm.get('factor_id')

        v_issues, v_warnings = validate_inputs(report_id, fsm, dpm, handoff, input_paths)
        issues.extend(v_issues)
        warnings.extend(v_warnings)
        implementation_path, path_notes = resolve_implementation_path(handoff, fsm)
        warnings.extend(path_notes)

        if implementation_path is None:
            issues.append({'severity': 'error', 'code': 'IMPLEMENTATION_PATH_MISSING', 'message': 'implementation path unresolved', 'evidence': {'resolution_order': ['handoff_to_step4', 'factor_spec_master']}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, None, dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'IMPLEMENTATION_PATH_MISSING', 'implementation_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        if issues:
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, implementation_path, dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'INPUT_VALIDATION_FAILED', 'input_validation', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        impl_path = Path(implementation_path)
        if not impl_path.is_absolute():
            impl_path = (FACTORFORGE / impl_path) if str(implementation_path).startswith('generated_code/') else (WORKSPACE / implementation_path)
        if not impl_path.exists():
            issues.append({'severity': 'error', 'code': 'IMPLEMENTATION_PATH_NOT_FOUND', 'message': 'resolved implementation path does not exist', 'evidence': {'path': str(impl_path)}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'IMPLEMENTATION_PATH_NOT_FOUND', 'implementation_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return
        base_identity = fill_runtime_implementation_identity(base_identity, fsm, impl_path)
        assert_direct_code_full_window_scope(fsm)

        # Frozen-schema execution: Step4 consumes either legacy normalized local
        # snapshots or the Step3 Data API contract. It must not guess raw paths or
        # build clean layers itself.
        local_inputs = handoff.get('local_input_paths') or dpm.get('local_input_paths') or {}
        step4_contract = _step4_data_contract(dpm, handoff)
        validate_pre_release_step4_data_access(dpm, handoff)
        evo_pre_release = isinstance(dpm.get('research_windows'), dict)
        if evo_pre_release:
            local_inputs, data_api_profile = validate_evo_pre_release_data_receipt(
                report_id=report_id,
                dpm=dpm,
                handoff=handoff,
                run_dir=run_dir,
            )
        else:
            data_api_profile = None
        local_is_delivery_receipt = (
            handoff.get('local_is_input_delivery_receipt')
            or dpm.get('local_is_input_delivery_receipt')
        )
        if local_is_delivery_receipt:
            if evo_pre_release:
                raise SystemExit(
                    'BLOCK_STEP4_LOCAL_IS_DELIVERY_RECEIPT_INVALID: evo_pre_release_forbidden'
                )
            data_api_profile = validate_local_is_delivery_receipt(
                receipt_path=local_is_delivery_receipt,
                contract=step4_contract,
                local_inputs=local_inputs,
            )
        force_contract_inputs = (
            False
            if evo_pre_release or data_api_profile is not None
            else bool(
                (step4_contract.get('full_queries') or {})
                if isinstance(step4_contract, dict)
                else False
            )
        )
        prepared_derived_state = (
            str(local_inputs.get('input_mode') or '') == 'derived_state_with_daily'
        )
        from factor_factory.prepared_daily_inputs import is_prepared_daily, validate_full_scope
        prepared_daily = is_prepared_daily(local_inputs)
        if (prepared_derived_state or prepared_daily) and (
            evo_pre_release or os.getenv('FACTORFORGE_LOCAL_IS_ONLY') != '1'
        ):
            raise SystemExit(
                'BLOCK_STEP4_PREPARED_DERIVED_STATE_LOCAL_IS_ONLY: '
                'prepared study-local state cannot be used for EVO/OOS or hosted execution'
            )
        legacy_daily_fallback = str(
            manifest_path(manifest, 'runs', 'step3a_daily_input_csv') or ''
        )
        try:
            if prepared_daily:
                try:
                    validate_full_scope(local_inputs, WORKSPACE, additional_workspace=implementation_workspace_root(
                        FACTORFORGE, manifest=manifest, legacy_workspace=WORKSPACE))
                except (ValueError, OSError, KeyError) as exc:
                    raise SystemExit(f'BLOCK_STEP4_PREPARED_DAILY_SCOPE: {exc}') from exc
            if not (prepared_derived_state or prepared_daily):
                local_inputs, data_api_profile = (
                    materialize_step4_contract_inputs_if_required(
                        report_id=report_id,
                        contract=step4_contract,
                        run_dir=run_dir,
                        local_inputs=local_inputs,
                        force_contract_inputs=force_contract_inputs,
                        evo_pre_release=evo_pre_release,
                        existing_profile=data_api_profile,
                        fallback_daily_path=legacy_daily_fallback,
                    )
                )
        except SystemExit as exc:
            if evo_pre_release:
                raise
            issues.append({
                'severity': 'error',
                'code': 'STEP4_DATA_INPUTS_MISSING',
                'message': str(exc),
                'evidence': {
                    'local_input_paths': local_inputs,
                    'step4_data_contract': _step4_data_contract(dpm, handoff),
                },
            })
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'STEP4_DATA_INPUTS_MISSING', 'execution_precheck', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return
        force_shared_context = (
            data_api_profile is not None
            or str(local_inputs.get('formula_input_dataset') or 'clean_daily_bar') != 'clean_daily_bar'
            or evo_diagnostic_contract is not None
        )
        parent_diagnostics_projection = parent_diagnostics_arrow_projection_eligible(
            prepared_derived_state=prepared_derived_state,
            custom_primary=custom_primary,
            local_is_only=os.getenv('FACTORFORGE_LOCAL_IS_ONLY') == '1',
            shared_context_enabled=(
                shared_evaluation_context_enabled(args.enable_shared_evaluation_context)
                or force_shared_context
            ),
        )
        minute_path = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
        minute_streaming_query = (
            local_inputs.get('minute_streaming_query')
            if isinstance(local_inputs.get('minute_streaming_query'), dict)
            else None
        )
        daily_path = (
            local_inputs.get('daily_df_parquet')
            or local_inputs.get('daily_df_csv')
            or legacy_daily_fallback
        )
        exchange_calendar_path = local_inputs.get('exchange_calendar_parquet')
        from factor_factory.implementation_runtime import load_named_inputs, named_input_bindings
        implementation_workspace = implementation_workspace_root(FACTORFORGE, manifest=manifest, legacy_workspace=WORKSPACE)
        if (minute_streaming_query or prepared_derived_state) and named_input_bindings(local_inputs):
            raise ValueError('BLOCK_FACTOR_IMPLEMENTATION_ADDITIONAL_INPUT_ROUTE_UNSUPPORTED: streaming/partitioned controller')
        additional_inputs, additional_paths = load_named_inputs(
            local_inputs, implementation_workspace,
            window=local_inputs['sample_window_actual'] if prepared_daily else None,
        )
        from factor_factory.implementation_runtime import implementation_input_identity
        implementation_inputs = implementation_input_identity(impl_path, implementation_workspace, additional_paths)
        input_mode = str(local_inputs.get('input_mode') or '')
        minute_required = bool(
            minute_path
            or minute_streaming_query
            or input_mode in {'price_volume_minute', 'minute_and_daily'}
        )
        if state_reuse_required:
            try:
                assert_no_raw_minute_full_window_scan(
                    input_paths=[
                        *(str(value) for value in local_inputs.values() if isinstance(value, str)),
                        *(json.dumps(value, ensure_ascii=False, sort_keys=True) for value in local_inputs.values() if isinstance(value, dict)),
                    ],
                    production=True,
                    explicit_data_production_context=False,
                )
            except StateReuseBlock as exc:
                raise SystemExit(str(exc)) from exc

        import pandas as pd  # local import to keep hard dependency only for real execution path
        minute_file = Path(minute_path) if minute_path else None
        daily_file = Path(daily_path)
        exchange_calendar_file = (
            Path(exchange_calendar_path) if exchange_calendar_path else None
        )
        derived_state_root = (
            Path(local_inputs['derived_state_root'])
            if prepared_derived_state else None
        )
        if minute_file is not None and not minute_file.is_absolute():
            minute_file = WORKSPACE / minute_file
        if not daily_file.is_absolute():
            daily_file = WORKSPACE / daily_file
        if exchange_calendar_file is not None and not exchange_calendar_file.is_absolute():
            exchange_calendar_file = WORKSPACE / exchange_calendar_file
        if derived_state_root is not None and not derived_state_root.is_absolute():
            derived_state_root = WORKSPACE / derived_state_root
        if (
            (minute_required and minute_file is not None and not minute_file.exists())
            or not daily_file.exists()
            or (exchange_calendar_file is not None and not exchange_calendar_file.exists())
        ):
            issues.append({'severity': 'error', 'code': 'LOCAL_INPUT_FILES_NOT_FOUND', 'message': 'declared local input files do not exist', 'evidence': {'minute': str(minute_file) if minute_file else None, 'daily': str(daily_file), 'exchange_calendar': str(exchange_calendar_file) if exchange_calendar_file else None}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'LOCAL_INPUT_FILES_NOT_FOUND', 'execution_precheck', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return
        if prepared_derived_state and (
            minute_file is not None
            or derived_state_root is None
            or not derived_state_root.is_dir()
        ):
            raise SystemExit(
                'BLOCK_STEP4_PREPARED_DERIVED_STATE_INPUT_INVALID: '
                'requires derived_state_root directory and forbids raw minute input'
            )

        def read_df(p: Path):
            if p.suffix.lower() == '.parquet':
                return pd.read_parquet(p)
            return pd.read_csv(p)

        parquet_path = run_dir / f'factor_values__{report_id}.parquet'
        csv_path = run_dir / f'factor_values__{report_id}.csv'
        sample_csv_path = run_dir / f'factor_values_sample__{report_id}.csv'
        meta_path = run_dir / f'run_metadata__{report_id}.json'
        step3b_cache_path = run_dir / f'step3b_sample_factor_values__{report_id}.parquet'
        step3b_cache_meta_path = run_dir / f'step3b_sample_run_metadata__{report_id}.json'
        existing_meta = load_json(meta_path) if meta_path.exists() else {}
        factor_csv_policy_observed = step4_factor_csv_policy_from_step3b(existing_meta)
        parquet_existed_before_step4 = parquet_path.exists()
        existing_factor_source = classify_existing_factor_parquet_source(existing_meta) if parquet_existed_before_step4 else {}
        may_reuse_existing_factor = False

        evaluation_daily_file = Path(local_inputs.get('evaluation_daily_df_parquet') or daily_file)
        if not evaluation_daily_file.is_absolute():
            evaluation_daily_file = WORKSPACE / evaluation_daily_file
        signal_daily_file = Path(local_inputs.get('signal_daily_df_parquet') or daily_file)
        if not signal_daily_file.is_absolute():
            signal_daily_file = WORKSPACE / signal_daily_file
        partitioned_controller_profile = None
        parent_diagnostics_projection_profiles: list[dict[str, Any]] = []
        parent_daily_summary: dict[str, Any] | None = None
        parent_factor_summary: dict[str, Any] | None = None
        minute_df = (
            read_df(minute_file)
            if minute_file is not None and not prepared_derived_state
            else (None if input_mode == 'daily_only' else pd.DataFrame())
        )
        exchange_calendar_df = (
            read_df(exchange_calendar_file)
            if exchange_calendar_file is not None else None
        )
        if parent_diagnostics_projection:
            parent_daily_summary, daily_profile = stream_parent_diagnostics_summary(
                signal_daily_file,
                PARENT_DIAGNOSTIC_DAILY_COLUMNS,
            )
            parent_diagnostics_projection_profiles.append(daily_profile)
            daily_df = signal_daily_df = None
            shared_canonical_daily_input = (
                evaluation_daily_file == signal_daily_file
                or evaluation_daily_file.samefile(signal_daily_file)
            )
        else:
            daily_df, signal_daily_df, shared_canonical_daily_input = read_evaluation_daily_frames(
                evaluation_daily_file,
                signal_daily_file,
                read_df,
            )
        if evo_pre_release:
            expected_receipt_artifacts = data_api_profile.pop(
                '_evo_receipt_artifacts', []
            )
            validate_evo_pre_release_artifacts_after_read(
                run_dir=run_dir,
                local_inputs=local_inputs,
                research_windows=dpm['research_windows'],
                contract=step4_contract,
                expected_artifacts=expected_receipt_artifacts,
            )
        expected_reuse_identity = build_step4_reuse_identity(
            report_id=report_id,
            factor_id=factor_id,
            base_identity=base_identity,
            dpm=dpm,
            daily_df=signal_daily_df,
            daily_stats=(
                parent_daily_summary if parent_diagnostics_projection else None
            ),
            daily_universe_hash=(
                parent_daily_summary.get('universe_hash')
                if parent_diagnostics_projection and parent_daily_summary is not None
                else None
            ),
        )
        if any(implementation_inputs.values()):
            expected_reuse_identity['data_catalog_hash'] = stable_json_hash({
                'declared_data_identity': expected_reuse_identity['data_catalog_hash'],
                'implementation_inputs': implementation_inputs,
            })
        existing_factor_reuse_gate = None
        if parquet_existed_before_step4:
            existing_factor_source, existing_factor_reuse_gate, may_reuse_existing_factor = resolve_existing_step4_formal_reuse(
                existing_meta,
                expected_reuse_identity,
                source_artifact=str(parquet_path),
            )
            if existing_factor_source.get('source') == 'step3b_sample_or_legacy_factor_parquet':
                existing_factor_reuse_gate = existing_factor_reuse_gate or {
                    'version': 'factorforge_reuse_gate_v1',
                    'source_artifact': str(parquet_path),
                }
                existing_factor_reuse_gate['decision'] = 'block_invalid_formal_reuse'
                existing_factor_reuse_gate['reason'] = 'step3b_sample_proof_not_formal_factor_values'
        if (
            prepared_derived_state
            and parquet_existed_before_step4
            and not may_reuse_existing_factor
        ):
            # The prepared controller creates this exact formal path.  A stale,
            # sample, or unreadable pre-existing artifact cannot be replaced as
            # a side effect of attempting a fresh compute.
            reuse_reason = (
                existing_factor_reuse_gate.get('reason')
                if isinstance(existing_factor_reuse_gate, dict)
                else existing_factor_source.get('source') or 'unknown_provenance'
            )
            raise SystemExit(
                'BLOCK_STEP4_EXISTING_FORMAL_PARQUET_REUSE_REJECTED:'
                f'{reuse_reason}'
            )
        if prepared_derived_state and not may_reuse_existing_factor:
            # Identity/readback checks above are intentionally completed before
            # invoking the create-only controller.  A matching Step4-owned
            # formal artifact must never be recomputed just because this route
            # normally writes the same output path.
            module = import_module_from_path(impl_path)
            if not callable(getattr(module, 'compute_factor_partitioned', None)):
                raise SystemExit(
                    'BLOCK_STEP4_PREPARED_DERIVED_STATE_CONTROLLER_MISSING: '
                    'implementation must define compute_factor_partitioned'
                )
            controller_result = run_partitioned_controller(
                module,
                local_inputs=local_inputs,
                derived_state_root=derived_state_root,
                daily_input_path=daily_file,
                output_path=parquet_path,
                run_dir=run_dir,
                report_id=report_id,
                factor_id=factor_id,
                factorforge_root=FACTORFORGE,
                workspace_root=WORKSPACE,
            )
            if parent_diagnostics_projection:
                if not isinstance(controller_result, Path):
                    raise SystemExit('BLOCK_STEP4_PARENT_DIAGNOSTICS_CONTROLLER_PATH_REQUIRED')
                parent_factor_summary, factor_projection_profile = stream_parent_diagnostics_summary(
                    controller_result,
                    PARENT_DIAGNOSTIC_FACTOR_COLUMNS,
                    signal_col='factor_value',
                )
                parent_diagnostics_projection_profiles.append(factor_projection_profile)
                result_df = None
            else:
                result_df = read_df(controller_result) if isinstance(controller_result, Path) else controller_result
            partitioned_controller_profile = {
                'mode': 'prepared_derived_state_partitioned_controller',
                'derived_state_root': str(derived_state_root),
                'daily_input_path': str(daily_file),
                'output_path': str(parquet_path),
            }
        input_io_profile = {
            'additional_input_paths': {name: str(path) for name, path in additional_paths.items()},
            'implementation_inputs': implementation_inputs,
            'source': 'local_snapshot' if data_api_profile is None else 'factorforge_data_api_full_query',
            'daily_selected_format': 'parquet' if daily_file.suffix.lower() == '.parquet' else 'csv',
            'daily_selected_path': str(daily_file),
            'formula_input_dataset': local_inputs.get('formula_input_dataset') or 'clean_daily_bar',
            'signal_daily_path': str(signal_daily_file),
            'evaluation_daily_path': str(evaluation_daily_file),
            'daily_parquet_path': str(WORKSPACE / local_inputs['daily_df_parquet']) if local_inputs.get('daily_df_parquet') and not Path(local_inputs['daily_df_parquet']).is_absolute() else local_inputs.get('daily_df_parquet'),
            'daily_csv_path': str(WORKSPACE / local_inputs['daily_df_csv']) if local_inputs.get('daily_df_csv') and not Path(local_inputs['daily_df_csv']).is_absolute() else local_inputs.get('daily_df_csv'),
            'data_api_profile': data_api_profile,
            'minute_streaming_enabled': bool(minute_streaming_query),
            'prepared_derived_state_root': (
                str(derived_state_root) if prepared_derived_state else None
            ),
            'prepared_derived_state_controller': bool(prepared_derived_state),
            'parent_diagnostics_projection': {
                'enabled': bool(parent_diagnostics_projection),
                'profiles': parent_diagnostics_projection_profiles,
                'full_factor_parquet_preserved': bool(parent_diagnostics_projection),
            },
            'state_datamart_reuse': state_datamart_reuse,
        }
        if isinstance(data_api_profile, dict):
            result_metadata = data_api_profile.get('result_metadata') if isinstance(data_api_profile.get('result_metadata'), dict) else {}
            daily_basic_meta = result_metadata.get('daily_basic') if isinstance(result_metadata.get('daily_basic'), dict) else {}
            daily_basic_perf = daily_basic_meta.get('performance_profile') if isinstance(daily_basic_meta.get('performance_profile'), dict) else {}
            backtest_base_profile = (
                data_api_profile.get('backtest_base_reuse_profile')
                if isinstance(data_api_profile.get('backtest_base_reuse_profile'), dict)
                else result_metadata.get('backtest_base_daily_controls_v1')
            )
            if isinstance(daily_basic_perf, dict) and daily_basic_perf:
                input_io_profile['daily_basic_reuse_profile'] = daily_basic_perf
                input_io_profile['daily_basic_selected_format'] = daily_basic_perf.get('daily_basic_selected_format')
                input_io_profile['daily_basic_cache_hit'] = daily_basic_perf.get('daily_basic_cache_hit')
                input_io_profile['daily_basic_cache_path'] = daily_basic_perf.get('daily_basic_cache_path')
                input_io_profile['daily_basic_rows'] = daily_basic_perf.get('daily_basic_rows')
                input_io_profile['daily_basic_dates'] = daily_basic_perf.get('daily_basic_dates')
                input_io_profile['daily_basic_tickers'] = daily_basic_perf.get('daily_basic_tickers')
                input_io_profile['daily_basic_load_seconds'] = daily_basic_perf.get('daily_basic_load_seconds')
            if isinstance(backtest_base_profile, dict) and backtest_base_profile:
                input_io_profile['backtest_base_reuse_profile'] = backtest_base_profile
                input_io_profile['backtest_base_reuse_hit'] = backtest_base_profile.get('backtest_base_reuse_hit')
                input_io_profile['backtest_base_cache_path'] = backtest_base_profile.get('backtest_base_cache_path')
        step3b_cache_source = {}
        if (
            not prepared_derived_state
            and not may_reuse_existing_factor
            and step3b_cache_path.exists()
            and step3b_cache_meta_path.exists()
        ):
            step3b_cache_source = classify_step3b_compute_cache_source(
                load_json(step3b_cache_meta_path),
                signal_daily_df,
                impl_path,
                expected_identity=expected_reuse_identity,
                source_artifact=str(step3b_cache_path),
            )
        if prepared_derived_state and not may_reuse_existing_factor:
            step4_factor_io_profile = {
                'version': 'factorforge_step4_factor_io_profile_v1',
                'source': 'step4_prepared_derived_state_partitioned_controller',
                'selected_factor_format': 'parquet',
                'selected_factor_path': str(parquet_path),
                'recomputed_factor': True,
                'parquet_existed_before_step4': bool(parquet_existed_before_step4),
                'parquet_written_by_step4': True,
                'prepared_derived_state_controller': partitioned_controller_profile,
                'reuse_gate': {
                    'version': 'factorforge_reuse_gate_v1',
                    'decision': 'recompute_required',
                    'matched_fields': [],
                    'mismatched_fields': [],
                    'missing_fields': [],
                    'source_artifact': str(parquet_path) if parquet_existed_before_step4 else None,
                    'reason': 'prepared_partitioned_controller_is_not_reused_before_execution',
                },
            }
        elif may_reuse_existing_factor:
            if parent_diagnostics_projection:
                parent_factor_summary, factor_projection_profile = stream_parent_diagnostics_summary(
                    parquet_path,
                    PARENT_DIAGNOSTIC_FACTOR_COLUMNS,
                    signal_col='factor_value',
                )
                parent_diagnostics_projection_profiles.append(factor_projection_profile)
                result_df = None
            else:
                result_df = read_df(parquet_path)
            step4_factor_io_profile = {
                'version': 'factorforge_step4_factor_io_profile_v1',
                **existing_factor_source,
                'selected_factor_format': 'parquet',
                'selected_factor_path': str(parquet_path),
                'recomputed_factor': False,
                'parquet_existed_before_step4': True,
                'parquet_written_by_step4': False,
                'reuse_gate': existing_factor_reuse_gate,
            }
        elif step3b_cache_source.get('reusable') is True:
            result_df = read_df(step3b_cache_path)
            step4_factor_io_profile = {
                'version': 'factorforge_step4_factor_io_profile_v1',
                **step3b_cache_source,
                'selected_factor_format': 'parquet',
                'selected_factor_path': str(step3b_cache_path),
                'formal_factor_path': str(parquet_path),
                'recomputed_factor': False,
                'parquet_existed_before_step4': bool(parquet_existed_before_step4),
                'parquet_written_by_step4': True,
                'reuse_gate': step3b_cache_source.get('reuse_gate'),
            }
        else:
            if evo_pre_release:
                install_agent_execution_isolation()
            module = import_module_from_path(impl_path)
            if not (hasattr(module, 'compute_factor') or hasattr(module, 'FACTOR')):
                issues.append({'severity': 'error', 'code': 'COMPUTE_FACTOR_MISSING', 'message': 'implementation module missing compute_factor', 'evidence': {'path': str(impl_path)}})
                run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'COMPUTE_FACTOR_MISSING', 'implementation_import', start_utc)
                write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
                write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
                write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
                return
            minute_streaming_profile = None
            intraday_flow_preagg_profile = None
            minute_derived_state_profile = None
            minute_derived_factor_profile = None
            if minute_streaming_query:
                try:
                    flow_requirement = _minute_flow_state_requirement(step4_contract, dpm)
                    minute_dates = _daily_trade_dates_for_minute_query(signal_daily_df, minute_streaming_query)
                    if flow_requirement:
                        flow_dataset_id = str(flow_requirement.get('dataset_id') or MINUTE_DERIVED_FLOW_STATE_V1)
                        if flow_dataset_id != MINUTE_DERIVED_FLOW_STATE_V1:
                            result_df, minute_derived_state_profile, minute_derived_factor_profile = (
                                compute_factor_from_data_api_minute_derived_state_batches(
                                    module,
                                    daily_df=signal_daily_df,
                                    requirement=flow_requirement,
                                    minute_query=minute_streaming_query,
                                )
                            )
                        else:
                            load_started = time.perf_counter()
                            flow_state_df, minute_derived_state_profile = _load_required_minute_flow_state(
                                requirement=flow_requirement,
                                daily_df=signal_daily_df,
                                minute_query=minute_streaming_query,
                            )
                            minute_derived_state_profile['phase_seconds'] = {
                                'load_derived_state': minute_derived_state_profile.get('load_seconds') or (time.perf_counter() - load_started),
                            }
                            result_df, minute_derived_factor_profile = compute_factor_from_minute_derived_state(
                                module,
                                daily_df=signal_daily_df,
                                flow_state_df=flow_state_df,
                                dataset_id=flow_dataset_id,
                            )
                    elif _generic_minute_full_window_forbidden(minute_dates):
                        raise SystemExit(
                            'BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN: '
                            f'generic minute streaming is forbidden for {len(minute_dates)} formal dates without '
                            f'{MINUTE_DERIVED_FLOW_STATE_V1}; run scripts/build_minute_derived_datamart.py or declare a derived-state contract.'
                        )
                    elif _supports_sp3_intraday_flow_fast_path(module):
                        result_df, intraday_flow_preagg_profile = compute_factor_intraday_flow_daily_preagg_contract(
                            daily_df=signal_daily_df,
                            minute_query=minute_streaming_query,
                            report_id=report_id,
                            run_dir=run_dir,
                        )
                    else:
                        result_df, minute_streaming_profile = compute_factor_streaming_minute_contract(
                            module,
                            daily_df=signal_daily_df,
                            minute_query=minute_streaming_query,
                            report_id=report_id,
                        )
                except SystemExit as exc:
                    token = str(exc).split(':', 1)[0]
                    issues.append({
                        'severity': 'error',
                        'code': token,
                        'message': str(exc),
                        'evidence': {
                            'minute_streaming_query': minute_streaming_query,
                            'minute_derived_state_requirements': _minute_derived_state_requirements(step4_contract, dpm),
                            'step4_data_contract': step4_contract,
                        },
                    })
                    run_master, diagnostics, handoff_out = build_failure_outputs(
                        report_id,
                        factor_id,
                        str(impl_path),
                        dpm.get('sample_window', {}),
                        run_dir,
                        input_paths,
                        issues,
                        warnings,
                        token,
                        'minute_derived_state_precheck',
                        start_utc,
                    )
                    write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
                    write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
                    write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
                    return
            else:
                result_df = compute_factor_with_contract(
                    module,
                    signal_daily_df,
                    minute_df,
                    exchange_calendar=exchange_calendar_df,
                    additional_inputs=additional_inputs,
                )
            if evo_pre_release:
                end_agent_execution_isolation()
            step4_factor_io_profile = {
                'version': 'factorforge_step4_factor_io_profile_v1',
                'source': (
                    'step4_minute_derived_flow_state_recompute'
                    if minute_derived_state_profile else
                    'step4_intraday_flow_daily_preagg_recompute'
                    if intraday_flow_preagg_profile else
                    ('step4_minute_streaming_recompute' if minute_streaming_query else 'step4_recompute_fallback')
                ),
                'prior_factor_parquet_source': existing_factor_source.get('source') if parquet_existed_before_step4 else None,
                'step3b_compute_cache_source': step3b_cache_source or None,
                'selected_factor_format': 'computed',
                'selected_factor_path': str(parquet_path),
                'recomputed_factor': True,
                'parquet_existed_before_step4': bool(parquet_existed_before_step4),
                'parquet_written_by_step4': True,
                'reuse_gate': (
                    (step3b_cache_source or {}).get('reuse_gate')
                    or existing_factor_reuse_gate
                    or {
                        'version': 'factorforge_reuse_gate_v1',
                        'decision': 'recompute_required',
                        'matched_fields': [],
                        'mismatched_fields': [],
                        'missing_fields': [],
                        'source_artifact': str(parquet_path) if parquet_existed_before_step4 else None,
                        'reason': 'no_reusable_identity_matched',
                    }
                ),
            }
            if intraday_flow_preagg_profile:
                step4_factor_io_profile['intraday_flow_daily_preagg_profile'] = intraday_flow_preagg_profile
            if minute_derived_state_profile:
                step4_factor_io_profile['minute_derived_state_profile'] = minute_derived_state_profile
            if minute_derived_factor_profile:
                step4_factor_io_profile['minute_derived_factor_profile'] = minute_derived_factor_profile
                step4_factor_io_profile['performance_phase_profile'] = {
                    'load_derived_state_seconds': float((minute_derived_state_profile or {}).get('load_seconds') or 0.0),
                    'factor_compute_seconds': float(minute_derived_factor_profile.get('factor_compute_seconds') or 0.0),
                    'evaluation_seconds': None,
                    'write_outputs_seconds': None,
                }
            if minute_streaming_profile:
                step4_factor_io_profile['minute_streaming_profile'] = minute_streaming_profile

        if (
            (parent_factor_summary is not None and int(parent_factor_summary.get('row_count') or 0) == 0)
            or (parent_factor_summary is None and (result_df is None or len(result_df) == 0))
        ):
            issues.append({'severity': 'error', 'code': 'EMPTY_MAIN_RESULT', 'message': 'main result not materially generated', 'evidence': {'rows': 0}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'EMPTY_MAIN_RESULT', 'execution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        if result_df is not None and not parent_diagnostics_projection:
            from factor_factory.research_api import validate_factor_output
            result_df = validate_factor_output(result_df)
        signal_col = (
            'factor_value'
            if parent_factor_summary is not None
            or (result_df is not None and 'factor_value' in result_df.columns)
            else infer_signal_column(result_df, factor_id=factor_id)
        )
        # A prepared direct-code controller can retain source-component audit
        # columns and a trailing ``warmup`` flag beside the declared standard
        # signal.  Keep an existing family-specific signal selected by the
        # helper, but never let its last-column fallback turn that boolean
        # diagnostic into the formal signal.
        if result_df is not None and signal_col == 'warmup' and 'factor_value' in result_df.columns:
            signal_col = 'factor_value'
        if (
            result_df is not None
            and {'ts_code', 'trade_date'}.issubset(result_df.columns)
            and not may_reuse_existing_factor
            and not parent_diagnostics_projection
        ):
            result_df = result_df.sort_values(
                ['ts_code', 'trade_date'], kind='mergesort'
            ).reset_index(drop=True)
        if not may_reuse_existing_factor and not prepared_derived_state:
            result_df.to_parquet(parquet_path, index=False)
        if (
            factor_csv_policy_observed.get('factor_csv_write_allowed')
            and not csv_path.exists()
            and not parent_diagnostics_projection
        ):
            result_df.to_csv(csv_path, index=False)
            step4_factor_io_profile['csv_written_by_step4'] = True
        else:
            step4_factor_io_profile['csv_written_by_step4'] = False
        factor_csv_policy_observed['factor_csv_written_by_step4'] = bool(
            step4_factor_io_profile['csv_written_by_step4']
        )
        if factor_csv_policy_observed.get('factor_csv_write_allowed') and not step4_factor_io_profile['csv_written_by_step4']:
            factor_csv_policy_observed['factor_csv_write_skipped_reason'] = (
                'parent_diagnostics_projection_preserves_full_parquet_only'
                if parent_diagnostics_projection
                else 'step3b_csv_already_available'
            )

        if parent_factor_summary is not None:
            row_count = int(parent_factor_summary['row_count'])
            date_count = int(parent_factor_summary['date_count'])
            ticker_count = int(parent_factor_summary['ticker_count'])
            actual_start = _normal_date_value(parent_factor_summary['start'])
            actual_end = _normal_date_value(parent_factor_summary['end'])
        else:
            row_count = int(len(result_df))
            date_count = int(result_df['trade_date'].nunique()) if 'trade_date' in result_df.columns else 0
            ticker_count = int(result_df['ts_code'].nunique()) if 'ts_code' in result_df.columns else 0
            actual_start = _normal_date_value(result_df['trade_date'].min()) if 'trade_date' in result_df.columns and row_count else None
            actual_end = _normal_date_value(result_df['trade_date'].max()) if 'trade_date' in result_df.columns and row_count else None
        target_window = dpm.get('sample_window', {}) or {}
        prepared_window = (dpm.get('local_input_paths') or {}).get('sample_window_actual') or {}
        research_window = _research_window_contract(step4_contract, dpm)
        target_start_raw = target_window.get('start')
        target_start = _normal_date_value(target_start_raw)
        target_end_raw = target_window.get('end')
        input_daily_start = (
            _normal_date_value(parent_daily_summary['start'])
            if parent_daily_summary is not None
            else _normal_date_value(signal_daily_df['trade_date'].min()) if 'trade_date' in signal_daily_df.columns and len(signal_daily_df) else None
        )
        input_daily_end = (
            _normal_date_value(parent_daily_summary['end'])
            if parent_daily_summary is not None
            else _normal_date_value(signal_daily_df['trade_date'].max()) if 'trade_date' in signal_daily_df.columns and len(signal_daily_df) else None
        )
        prepared_start = _normal_date_value(prepared_window.get('start'))
        prepared_end = _normal_date_value(prepared_window.get('end'))
        # Step3B sample snapshots may leave a short sample_window_actual in
        # data_prep_master. Once Step4 has materialized the formal Data API
        # full-query input, that sample window must not cap Step4 coverage.
        # A validated ordinary local-IS delivery is the full contract input as
        # surely as an in-process Data API materialization. ``force`` is
        # disabled after receipt validation to avoid a redundant network fetch,
        # so it cannot also serve as the coverage discriminator.
        full_contract_input = is_full_contract_input_profile(
            data_api_profile,
            force_contract_inputs=force_contract_inputs,
        )
        if full_contract_input:
            effective_target_start = input_daily_start or target_start
            effective_target_end = input_daily_end if str(target_end_raw) == 'current' else (input_daily_end or _normal_date_value(target_end_raw))
        else:
            effective_target_start = prepared_start or input_daily_start or target_start
            if str(target_end_raw) == 'current':
                effective_target_end = input_daily_end
            else:
                effective_target_end = prepared_end or _normal_date_value(target_end_raw)
        target_end = effective_target_end
        coverage_complete = (actual_start == effective_target_start and actual_end == effective_target_end)
        run_status = 'success' if coverage_complete else 'partial'
        failure_reason = None
        sparse_signal_allowed = bool(
            step4_contract.get('sparse_signal_allowed')
            or dpm.get('sparse_signal_allowed')
            or handoff.get('sparse_signal_allowed')
        )
        canonical_spec = fsm.get('canonical_spec') if isinstance(fsm.get('canonical_spec'), dict) else {}
        formula_ir = canonical_spec.get('formula_ir') if isinstance(canonical_spec.get('formula_ir'), dict) else None
        formula_max_lookback = max_formula_ir_lookback(formula_ir)
        formal_signal_coverage = (
            build_formal_signal_coverage_profile_from_stream_summary(
                summary=parent_factor_summary,
                signal_col=signal_col,
                actual_start=actual_start,
                actual_end=actual_end,
                effective_target_start=effective_target_start,
                effective_target_end=effective_target_end,
                sparse_signal_allowed=sparse_signal_allowed,
                formula_max_lookback=formula_max_lookback,
            )
            if parent_factor_summary is not None
            else build_formal_signal_coverage_profile(
                result_df=result_df,
                signal_col=signal_col,
                actual_start=actual_start,
                actual_end=actual_end,
                effective_target_start=effective_target_start,
                effective_target_end=effective_target_end,
                sparse_signal_allowed=sparse_signal_allowed,
                formula_max_lookback=formula_max_lookback,
            )
        )
        if formal_signal_coverage.get('coverage_gate_verdict') == 'BLOCK':
            token = 'BLOCK_STEP4_FORMAL_SIGNAL_NON_NULL_COVERAGE_LOW'
            issues.append({
                'severity': 'error',
                'code': token,
                'message': 'formal Step4 factor values have insufficient non-null signal coverage for promotion-gate evidence',
                'evidence': formal_signal_coverage,
            })
            run_status = 'failed'
            failure_reason = token
        web_evaluation_contract = (
            fsm.get('evaluation_contract')
            if isinstance(fsm.get('evaluation_contract'), dict)
            and fsm.get('evaluation_contract', {}).get('version')
            == WEB_EVALUATION_CONTRACT_VERSION
            else None
        )
        if evo_diagnostic_contract is not None:
            if web_evaluation_contract is None:
                raise ValueError('BLOCK_FACTORFORGE_EVO_CHILD_WEB_EVALUATION_CONTRACT_REQUIRED')
            web_evaluation_contract = json.loads(json.dumps(web_evaluation_contract))
            addendum_ref = evo_diagnostic_contract.get('execution_addendum_ref')
            diagnostic_trials: list[dict[str, Any]] = []
            if isinstance(addendum_ref, dict):
                addendum_path = Path(str(addendum_ref.get('path') or '')).expanduser()
                if not addendum_path.is_absolute():
                    addendum_path = FACTORFORGE / addendum_path
                addendum = load_json(addendum_path)
                diagnostic_trials = [
                    {
                        'trial_id': test['test_id'],
                        'formula_or_law': test['formula_or_law'],
                        'signal_column': test['signal_column'],
                    }
                    for test in (addendum.get('execution_tests') or [])
                    if isinstance(test, dict)
                    and test.get('implementation_mode') == 'FORMULA_DIAGNOSTIC'
                ]
            existing_diagnostics = list(web_evaluation_contract.get('diagnostic_trials') or [])
            existing_ids = {
                str(item.get('trial_id') or '')
                for item in existing_diagnostics
                if isinstance(item, dict)
            }
            if any(item['trial_id'] in existing_ids for item in diagnostic_trials):
                raise ValueError('BLOCK_FACTORFORGE_EVO_CHILD_DIAGNOSTIC_TRIAL_COLLISION')
            web_evaluation_contract['diagnostic_trials'] = [
                *existing_diagnostics,
                *diagnostic_trials,
            ]
        shared_context_version = (
            'factorforge_shared_evaluation_context_v2'
            if web_evaluation_contract is not None
            else 'factorforge_shared_evaluation_context_v1'
        )
        shared_context: dict[str, Any] | None = None
        shared_context_profile: dict[str, Any] = {
            'version': shared_context_version,
            'enabled': False,
            'built': False,
            'used_by_step4': False,
            'context_path': None,
            'build_seconds': 0.0,
            'invalidated_reason': 'not_enabled',
        }
        if shared_evaluation_context_enabled(args.enable_shared_evaluation_context) or force_shared_context:
            shared_context = build_shared_evaluation_context(
                report_id=report_id,
                factor_id=factor_id,
                implementation_mode_decision=implementation_mode_decision,
                base_identity=base_identity,
                run_dir=run_dir,
                factor_df=result_df,
                daily_df=daily_df,
                signal_col=signal_col,
                factor_parquet_path=parquet_path,
                daily_input_path=evaluation_daily_file,
                target_window=target_window,
                effective_target_window={'start': effective_target_start, 'end': effective_target_end},
                evaluation_contract=web_evaluation_contract,
                signal_daily_df=signal_daily_df,
                signal_daily_input_path=signal_daily_file,
                exchange_calendar=exchange_calendar_df,
                pre_release_research_windows=(
                    dpm.get('research_windows')
                    if isinstance(dpm.get('research_windows'), dict)
                    else None
                ),
            )
            shared_context_profile = {
                'version': shared_context_version,
                'enabled': True,
                'built': True,
                'used_by_step4': False,
                'context_path': ((shared_context.get('paths') or {}).get('context_json')),
                'build_seconds': shared_context.get('build_seconds'),
                'invalidated_reason': None,
                'row_counts': shared_context.get('row_counts'),
            }
        evo_child_execution: dict[str, Any] | None = None
        if evo_diagnostic_contract is not None:
            if shared_context is None:
                raise ValueError('BLOCK_FACTORFORGE_EVO_CHILD_SHARED_CONTEXT_REQUIRED')
            try:
                evo_child_execution = materialize_evo_child_execution_result(
                    workspace_root=FACTORFORGE,
                    parent_report_id=str(evo_diagnostic_contract['parent_report_id']),
                    child_report_id=report_id,
                    diagnostic_contract=evo_diagnostic_contract,
                    expected_host_trust_manifest_sha256=(
                        args.expected_host_trust_manifest_sha256
                    ),
                )
            except EvoChildExecutionError as exc:
                raise ValueError(';'.join(exc.reasons)) from exc
        # Compute small output diagnostics before releasing the parent's full
        # factor frame. Custom backend processes load the persisted parquet.
        if parent_factor_summary is not None:
            null_ratio = {
                signal_col: float(1.0 - (int(parent_factor_summary['non_null']) / row_count))
            } if row_count else {}
            duplicate_ratio = {
                'ts_code_trade_date': parent_factor_summary.get('duplicate_ratio')
            }
            sort_order_ok = bool(parent_factor_summary.get('key_order_ok'))
        else:
            null_ratio = {}
            for col in [signal_col]:
                if col in result_df.columns and row_count:
                    null_ratio[col] = float(result_df[col].isna().mean())
            duplicate_ratio = {}
            if {'ts_code', 'trade_date'}.issubset(result_df.columns):
                duplicate_ratio['ts_code_trade_date'] = float(result_df.duplicated(['ts_code', 'trade_date']).mean())
            sort_order_ok = True
            if {'ts_code', 'trade_date'}.issubset(result_df.columns):
                sort_order_ok = result_df[['ts_code', 'trade_date']].reset_index(drop=True).equals(
                    result_df.sort_values(['ts_code', 'trade_date'])[['ts_code', 'trade_date']].reset_index(drop=True)
                )
        daily_df, signal_daily_df, minute_df, parent_evaluation_frames_released = (
            release_parent_evaluation_frames_for_custom_primary(
                custom_primary,
                daily_df,
                signal_daily_df,
                minute_df,
            )
        )
        if parent_evaluation_frames_released:
            result_df = None
            if prepared_derived_state:
                controller_result = None
            release_parent_arrow_buffers()
        backend_runs = build_backend_runs_stub(report_id, evaluation_plan, run_status)
        backend_runs, backend_timing_profile = write_backend_payloads(
            report_id,
            backend_runs,
            manifest_path_arg=manifest_path_arg,
            exchange_calendar_path=exchange_calendar_file,
            shared_context=shared_context,
            factor_parquet_path=parquet_path,
        )
        backend_timing_profile['shared_evaluation_context'] = {
            'enabled': bool(shared_context),
            'built': bool(shared_context),
            'build_seconds': shared_context_profile.get('build_seconds') if shared_context else 0.0,
            'context_path': shared_context_profile.get('context_path') if shared_context else None,
        }
        backend_timing_profile['parent_evaluation_frames'] = {
            'canonical_daily_input_read_once': shared_canonical_daily_input,
            'released_before_custom_primary_backend': parent_evaluation_frames_released,
            'factor_frame_released_before_custom_primary_backend': parent_evaluation_frames_released,
        }

        step4_owned_meta = {
            'report_id': report_id,
            'factor_id': factor_id,
            'implementation_mode_decision': implementation_mode_decision,
            'implementation_path': str(impl_path),
            'started_at_utc': start_utc,
            'finished_at_utc': utc_now(),
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'signal_column': signal_col,
            'actual_window': {'start': actual_start, 'end': actual_end},
            'target_window': target_window,
            'effective_target_window': {'start': effective_target_start, 'end': effective_target_end},
            'run_status_candidate': run_status,
            'input_io_profile': input_io_profile,
            'step4_factor_io_profile': step4_factor_io_profile,
            'formal_signal_coverage': formal_signal_coverage,
            'step4_formal_factor_identity': expected_reuse_identity,
            'step4_factor_csv_policy_observed': factor_csv_policy_observed,
            'state_datamart_reuse': state_datamart_reuse,
            'shared_evaluation_context': shared_context_profile,
            'evo_transfer_diagnostic_contract': evo_diagnostic_contract,
            'evo_child_execution': evo_child_execution,
            'backend_timing_profile': backend_timing_profile,
            'research_window_contract': research_window,
        }
        meta = merge_run_metadata(existing_meta, step4_owned_meta)
        write_json(meta_path, meta)
        step4_output_paths = output_paths_for_policy(parquet_path, csv_path, sample_csv_path, meta_path, factor_csv_policy_observed)

        run_master_path = OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json'
        diag_path = OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json'
        handoff_path = OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json'

        run_master = {
            'report_id': report_id,
            'factor_id': factor_id,
            'artifact_identity': derive_identity(base_identity, 'factor_run_master'),
            'run_status': run_status,
            'implementation_path': str(impl_path),
            'output_paths': step4_output_paths,
            'sample_window': target_window,
            'runtime_notes': warnings,
            'diagnostic_summary': {'row_count': row_count, 'date_count': date_count, 'ticker_count': ticker_count},
            'signal_column': signal_col,
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'backend_timing_profile': backend_timing_profile,
            'shared_evaluation_context': shared_context_profile,
            'evo_transfer_diagnostic_contract': evo_diagnostic_contract,
            'evo_child_execution': evo_child_execution,
            'implementation_mode_decision': implementation_mode_decision,
            'failure_reason': failure_reason,
            'started_at_utc': start_utc,
            'finished_at_utc': utc_now(),
            'input_paths': {k: str(v) for k, v in input_paths.items()},
            'input_io_profile': input_io_profile,
            'window_coverage': {
                'target_start': target_window.get('start'),
                'target_end': target_window.get('end'),
                'effective_target_start': effective_target_start,
                'effective_target_end': effective_target_end,
                'input_daily_start': input_daily_start,
                'input_daily_end': input_daily_end,
                'actual_start': actual_start,
                'actual_end': actual_end,
                'coverage_complete': coverage_complete,
            },
            'formal_signal_coverage': formal_signal_coverage,
            'validation_pointer': str(diag_path),
            'handoff_to_step5_path': str(handoff_path),
        }

        diagnostics = {
            'report_id': report_id,
            'factor_id': factor_id,
            'run_status': run_status,
            'diagnostic_generated_at_utc': utc_now(),
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'implementation_mode_decision': implementation_mode_decision,
            'input_validation': {
                'exists_check': {k: v.exists() for k, v in input_paths.items()},
                'input_io_profile': input_io_profile,
                'step4_factor_io_profile': step4_factor_io_profile,
                'step4_factor_csv_policy_observed': factor_csv_policy_observed,
                'backend_timing_profile': backend_timing_profile,
                'shared_evaluation_context': shared_context_profile,
                'schema_check': {'frozen_schema_execution': True},
                'consistency_check': {
                    'report_id_consistent': True,
                    'factor_id_consistent': True
                },
                'placeholder_check': {
                    'factor_spec_master_has_placeholder': contains_placeholder(fsm),
                    'data_prep_master_has_placeholder': contains_placeholder(dpm),
                    'handoff_to_step4_has_placeholder': contains_placeholder(handoff)
                }
            },
            'execution_trace': {
                'implementation_path': str(impl_path),
                'commands': [f'python3 skills/factor-forge-step4/scripts/run_step4.py --report-id {report_id}'],
                'runtime_seconds': None,
                'exception_type': None,
                'exception_message': None
            },
            'output_validation': {
                'output_exists': True,
                'output_paths': step4_output_paths,
                'file_sizes': file_sizes_for_paths(step4_output_paths),
                'row_count': row_count,
                'date_count': date_count,
                'ticker_count': ticker_count,
                'signal_column': signal_col,
                'formal_signal_coverage': formal_signal_coverage,
            },
            'quality_checks': {
                'window_complete': coverage_complete,
                'null_ratio': null_ratio,
                'formal_signal_coverage': formal_signal_coverage,
                'duplicate_ratio': duplicate_ratio,
                'key_uniqueness': {'ts_code_trade_date_unique': duplicate_ratio.get('ts_code_trade_date', 0.0) == 0.0},
                'sort_order_ok': sort_order_ok
            },
            'issues': issues,
            'failure_context': {
                'failed_stage': None,
                'failure_reason': None,
                'retryable': False
            },
            'recommendation': {
                'can_handoff_to_step5': run_status in {'success', 'partial'},
                'recommended_status': run_status,
                'next_action': (
                    'Proceed to Step 5 using declared evaluation scope.'
                    if run_status in {'success', 'partial'}
                    else 'Fix formal signal coverage and rerun Step 4 before Step 5/6.'
                )
            }
        }

        # COMMENT_POLICY: execution_handoff
        # Step 4 emits a stable handoff envelope for Step 5 to avoid implicit coupling.
        handoff_out = {
            'report_id': report_id,
            'factor_id': factor_id,
            'artifact_identity': derive_identity(base_identity, 'handoff_to_step5'),
            'run_status': run_status,
            'factor_run_master_path': str(run_master_path),
            'diagnostics_path': str(diag_path),
            'output_paths': step4_output_paths,
            'sample_window_target': target_window,
            'sample_window_actual': {'start': actual_start, 'end': actual_end},
            'coverage_ratio': 1.0 if coverage_complete else None,
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'signal_column': signal_col,
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'backend_timing_profile': backend_timing_profile,
            'shared_evaluation_context': shared_context_profile,
            'evo_transfer_diagnostic_contract': evo_diagnostic_contract,
            'evo_child_execution': evo_child_execution,
            'implementation_mode_decision': implementation_mode_decision,
            'key_warnings': warnings,
            'failure_reason': failure_reason,
            'can_enter_step5': run_status in {'success', 'partial'},
            'recommended_step5_scope': (
                'full'
                if run_status == 'success'
                else 'partial_scope_only'
                if run_status == 'partial'
                else None
            ),
            'notes_for_step5': (
                ['partial result: evaluate only covered window/instruments']
                if run_status == 'partial'
                else ['full result ready for evaluation']
                if run_status == 'success'
                else ['Step4 formal signal coverage failed; do not evaluate or promote.']
            )
        }

        acceptance_summary = build_acceptance_summary(
            report_id=report_id,
            factor_id=factor_id,
            run_status=run_status,
            output_paths=step4_output_paths,
            backend_runs=backend_runs,
            backend_timing_profile=backend_timing_profile,
            step4_factor_io_profile=step4_factor_io_profile,
            input_io_profile=input_io_profile,
        )
        run_master = add_formal_acceptance_envelope(
            run_master,
            identity=run_master['artifact_identity'],
            run_status=run_status,
            acceptance_summary=acceptance_summary,
        )
        handoff_out = add_formal_acceptance_envelope(
            handoff_out,
            identity=handoff_out['artifact_identity'],
            run_status=run_status,
            acceptance_summary=acceptance_summary,
        )

        write_json(run_master_path, run_master)
        write_json(diag_path, diagnostics)
        write_json(handoff_path, handoff_out)
    except Exception as e:
        issues.append({'severity': 'error', 'code': 'UNHANDLED_EXCEPTION', 'message': str(e), 'evidence': {'traceback': traceback.format_exc()[-4000:]}})
        run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, implementation_path, dpm.get('sample_window', {}) if dpm else {}, run_dir, input_paths, issues, warnings, type(e).__name__, 'unhandled_exception', start_utc)
        diagnostics['execution_trace']['exception_type'] = type(e).__name__
        diagnostics['execution_trace']['exception_message'] = str(e)
        diagnostics['issues'] = issues
        write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
        write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
        write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
        raise
