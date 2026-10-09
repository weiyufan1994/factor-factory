#!/usr/bin/env python3
"""Compatibility CLI; use factor_factory.step6.packets from Python."""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.step6.packets import (
    build_researcher_packet,
    load_json,
    file_info,
    compact_json,
    main,
)


def build_researcher_memo(rid, paths, objects, backend_payloads):
    """Legacy automatic memo generation is retired; existing reviews are preserved."""
    raise RuntimeError("Evidence preparation does not author a researcher memo; supply an independent research review.")


if __name__ == "__main__":
    main()
