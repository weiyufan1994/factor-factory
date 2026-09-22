from __future__ import annotations

from pathlib import Path


def discover_miner_campaigns(roots: list[str | Path] | tuple[str | Path, ...]) -> list[Path]:
    """Find complete Miner campaign workspaces without scanning data/clean."""
    found: list[Path] = []
    seen: set[Path] = set()
    for root_value in roots:
        root = Path(root_value)
        miner_root = root / "factor_research" / "miner"
        if not miner_root.exists():
            continue
        for inventory in sorted(miner_root.glob("*/objects/miner_capability_inventory.json")):
            workspace = inventory.parent.parent
            resolved = workspace.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(workspace)
    return found
