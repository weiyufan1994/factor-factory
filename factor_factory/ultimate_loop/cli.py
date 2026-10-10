"""Command-line parsing only; help does not load research or data services."""
from __future__ import annotations

import argparse
import sys


def build_parser(*, show_all: bool = False) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run or resume Factor Forge Step2–6.",
        epilog="Use --help-all for Council/search, state-data, hosted and compatibility options.",
    )
    groups = {title: ap.add_argument_group(title) for title in (
        "Research", "Council and search", "State data", "Hosted research",
        "Compatibility and optional observations",
    )}
    groups["Research"].add_argument('--report-id', required=True)
    groups["Research"].add_argument('--start-step', default='3', help='2, 3, 3b, 4, 5, or 6')
    groups["Research"].add_argument('--end-step', default='6', help='2, 3, 3b, 4, 5, 6, or all')
    groups["Research"].add_argument(
        '--local-is-only', action='store_true',
        help='Run local IS research without Host identity; never release OOS or issue hosted proof.',
    )
    groups["Research"].add_argument(
        '--prepared-local-inputs',
        default=None,
        help='Explicit study-local daily/derived-state input JSON for the local-IS Step3 route.',
    )
    groups["Research"].add_argument('--factorforge-root', default=None)
    groups["Research"].add_argument('--branch-id', default=None)
    groups["Research"].add_argument('--manifest', default=None, help='Use an existing runtime manifest instead of creating a new one.')
    groups["Research"].add_argument('--factor-id', default=None)
    groups["Research"].add_argument('--research-id', default=None)
    groups["Research"].add_argument('--factor-workspace', default=None)
    groups["Research"].add_argument('--init-factor-workspace', action='store_true')
    groups["Compatibility and optional observations"].add_argument('--allow-legacy-global-runtime', action='store_true')
    groups["Research"].add_argument('--skip-step3a', action='store_true', help='When starting at Step3, skip run_step3 and run only Step3B onward.')
    groups["Council and search"].add_argument('--skip-researcher-packets', action='store_true', help='Do not build Step6 researcher packet/dossier before Step6.')
    groups["Council and search"].add_argument('--council-mode', choices=['off', 'auto', 'scaffold', 'agentic'], default='auto')
    groups["Council and search"].add_argument('--auto-council-policy', choices=['scaffold', 'dispatch_manifest', 'block_without_agentic'], default='dispatch_manifest')
    groups["Council and search"].add_argument('--research-loop-policy', choices=['single_pass', 'council_until_promote_or_exhausted'], default='council_until_promote_or_exhausted')
    groups["Council and search"].add_argument('--max-council-loops', type=int, default=10)
    groups["Council and search"].add_argument('--agentic-council-executor', choices=['none', 'local_mock', 'dispatch_manifest', 'real_agent'], default='none')
    groups["Council and search"].add_argument('--agentic-dispatch-adapter', choices=['none', 'manual_file', 'openclaw', 'codex', 'remote_api'], default='none')
    groups["Council and search"].add_argument('--runtime-dispatch', choices=['codex', 'openclaw', 'manual_file', 'unknown'], default=None)
    groups["Council and search"].add_argument('--subagent-provider', default=None)
    groups["Council and search"].add_argument('--subagent-model', default=None)
    groups["Hosted research"].add_argument(
        '--research-org-mode',
        choices=['off', 'auto', 'required'],
        default='auto',
        help='Validate the workspace research-organization plan; required fails closed when absent.',
    )
    groups["Hosted research"].add_argument(
        '--research-org-plan',
        default=None,
        help='Explicit plan path. It must equal the active workspace Host-owned plan path.',
    )
    groups["Hosted research"].add_argument(
        '--research-org-runtime-mode',
        choices=['off', 'if-present', 'required', 'formal-complete', 'revision-child-assured'],
        default='off',
        help='Optionally bind this Ultimate run to the validated specialist runtime.',
    )
    groups["Hosted research"].add_argument('--research-org-runtime-private-root', default=None)
    groups["Hosted research"].add_argument('--research-org-runtime-trust-root', default=None)
    groups["Hosted research"].add_argument('--research-org-runtime-installation-id', default=None)
    groups["Hosted research"].add_argument('--evo-child-research-org-assurance', default=None)
    groups["Hosted research"].add_argument(
        '--expected-host-trust-manifest-sha256',
        default=None,
        help=(
            'Externally pinned Host public trust-manifest digest used to replay '
            'formal EVO child contracts. It must come from the Host control '
            'plane, not from the mutable workspace.'
        ),
    )
    groups["Hosted research"].add_argument(
        '--sealed-oos-carrier',
        default=None,
        help='Host-private fresh OOS dataset exposed only after NQC release.',
    )
    groups["Hosted research"].add_argument(
        '--sealed-oos-private-root',
        default=None,
        help='Externally pinned Host-private root containing the sealed OOS carrier.',
    )
    groups["Hosted research"].add_argument(
        '--sealed-oos-agent-visible-root',
        action='append',
        default=[],
        help='Host-pinned root mounted into an Agent runtime; repeat as needed.',
    )
    groups["Hosted research"].add_argument(
        '--agent-execution-sandbox-profile',
        default=None,
        help=(
            'Deprecated and forbidden for EVO child execution. A caller-owned '
            'profile is not execution authority; use the signed admission.'
        ),
    )
    groups["Hosted research"].add_argument(
        '--agent-execution-sandbox-admission',
        default=None,
        help=(
            'Deprecated and forbidden for EVO child execution. Production child '
            'Agent stages require the dedicated signed container admission.'
        ),
    )
    groups["Hosted research"].add_argument(
        '--agent-execution-container-admission',
        default=None,
        help=(
            'Host-private signed admission for the closed EVO child Step3B/Step4 '
            'container runner. Required for every non-dry-run EVO child.'
        ),
    )
    groups["Hosted research"].add_argument(
        '--evo-child-finalizer-recovery-admission',
        default=None,
        help=(
            'Host-private signed CHILD_RECOVERY_READY receipt. It authorizes '
            'only the Host finalizer after a completed validate_step4 crash.'
        ),
    )
    groups["Hosted research"].add_argument(
        '--evo-child-command-recovery-admission',
        default=None,
        help=(
            'Host-private signed exact-command recovery admission for a '
            'RUNNING EVO child proof. Direct unsigned command skipping is forbidden.'
        ),
    )
    groups["Research"].add_argument('--dry-run', action='store_true')
    groups["Compatibility and optional observations"].add_argument(
        '--epistemic-step1-shadow-request',
        default=None,
        help=(
            'Optional isolated candidate request observed before Step2. '
            'Default off; never enters the formal command/proof contract.'
        ),
    )
    groups["Compatibility and optional observations"].add_argument(
        '--epistemic-failure-shadow-request',
        default=None,
        help=(
            'Optional isolated candidate failure-diagnosis request observed '
            'after a non-EVO Step5-only run. Default off and non-authoritative.'
        ),
    )
    groups["Council and search"].add_argument(
        '--hybrid-research-request',
        default=None,
        help=(
            'Optional local-IS development request for the bounded hybrid-research adapter. '
            'Default off; produces researcher evidence but never formal Step2/Step6 approval.'
        ),
    )
    groups["Council and search"].add_argument(
        '--hybrid-research-adapter-only',
        action='store_true',
        help=(
            'Run only the explicitly requested local hybrid-research bridge against an '
            'existing Ultimate object root; never emits formal proof or approval.'
        ),
    )
    groups["Council and search"].add_argument(
        '--hybrid-research-response',
        default=None,
        help='Optional real external researcher B response JSON to bind to an existing hybrid run.',
    )
    groups["Council and search"].add_argument('--hybrid-research-response-run-id', default=None)
    groups["Council and search"].add_argument('--hybrid-research-response-input-identity', default=None)
    groups["Council and search"].add_argument('--hybrid-research-response-material-sha256', default=None)
    groups["Council and search"].add_argument('--hybrid-research-response-erratum', default=None)
    groups["Council and search"].add_argument(
        '--hybrid-research-response-only',
        action='store_true',
        help=(
            'Record one explicitly bound local researcher response; never reruns search, '
            'updates policy, dispatches work, or grants formal approval.'
        ),
    )
    groups["Compatibility and optional observations"].add_argument('--allow-legacy-research-protocol-smoke', action='store_true', help=argparse.SUPPRESS)
    groups["Research"].add_argument('--proof-output', default=None)
    groups["State data"].add_argument('--state-dependency-contract', default=None)
    groups["State data"].add_argument('--state-catalog', default=None)
    groups["State data"].add_argument('--state-resolution', default=None)
    groups["State data"].add_argument('--state-data-request-dir', default=None)
    groups["State data"].add_argument('--state-input-path', action='append', default=[], help='Step4 input path to check for forbidden production raw-minute roots.')
    groups["State data"].add_argument('--require-state-reuse-contract', action='store_true')
    groups["State data"].add_argument('--explicit-data-production-context', action='store_true')
    ap.add_argument("--help-all", action="help", help="Show all supported options and defaults.")
    for title, group in groups.items():
        for action in group._group_actions:
            if show_all and action.help == argparse.SUPPRESS:
                action.help = "Legacy compatibility option; existing scope restrictions apply."
            elif not show_all and title != "Research":
                action.help = argparse.SUPPRESS
    return ap


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    arguments = sys.argv[1:] if argv is None else argv
    return build_parser(show_all="--help-all" in arguments).parse_args(arguments)
