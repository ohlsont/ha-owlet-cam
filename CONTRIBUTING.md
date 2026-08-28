# Contributing to Owlet Cam

Thank you for improving this unofficial Home Assistant integration. Stability,
secret safety and clean-room licensing take priority over feature breadth.

## Before opening an issue

- Read the [README](README.md), [beta checklist](docs/BETA_TESTING.md), and
  existing Issues and Discussions.
- Ask setup questions in GitHub Discussions. Open a bug only when the behavior
  is reproducible.
- Use private vulnerability reporting for security problems.
- Never publish an application package, `.owletcam` package, native library,
  SDK key, account or camera credential, token, identifier, private media, or
  unredacted local path.

## Clean-room boundary

Protocol observations may be used as factual references, but do not copy source
from an unlicensed or incompatible repository, decompiled application code,
native headers without redistribution rights, or proprietary binary material.
Record new references, the exact inspected revision and licence determination in
`REFERENCE_VERSIONS.md`. Implement behavior independently and cover it with
hand-authored tests.

## Development setup

Use [uv](https://docs.astral.sh/uv/) and the Python version declared by the
project:

```bash
uv sync --all-groups
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy custom_components scripts
uv run python scripts/check_secrets.py
uv run python scripts/validate_release.py
```

Add targeted tests for every behavior change. Archive extraction, subprocess,
redaction, config-flow and lifecycle changes require regression coverage.

## Pull requests

- Keep a pull request focused and explain its Home Assistant-visible outcome.
- Preserve external bridge mode when changing embedded behavior.
- Keep all native protocol work outside the Home Assistant Python process.
- Keep internal listeners loopback-only and secrets out of command-line
  arguments, environment variables, URLs, logs and diagnostics.
- Update the changelog and documentation when behavior changes.
- Record only tests actually performed; never infer real frames, audible audio,
  an outage recovery, architecture compatibility, or a soak-test result.

Contributions may be declined when their licence or secret provenance cannot be
established safely.
