#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.model_broker import ModelBrokerConfig, serve_model_broker  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fixed-destination Factor Forge model broker.")
    parser.add_argument("--api-key-file", required=True)
    parser.add_argument("--host", default="172.29.0.1")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--allowed-network", default="172.29.0.0/24")
    args = parser.parse_args()
    config = ModelBrokerConfig(
        api_key_file=Path(args.api_key_file),
        listen_host=args.host,
        listen_port=args.port,
        allowed_network=args.allowed_network,
    )
    serve_model_broker(config)


if __name__ == "__main__":
    main()
