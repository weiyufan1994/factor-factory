# factorforge

FactorForge workspace-local build.

## Runtime policy
- Python runtime for module 1 lives at `factorforge/.venv`
- Do not install PDF parser dependencies into system Python
- Use `factorforge/.venv/bin/python` for module 1 extraction and smoke tests

## Current module 1 dependency baseline
- pypdf
