# Test report

Evidence is recorded conservatively. “Passed” is used only with captured test
or real-system evidence.

| Milestone | Commit | Integration version | Home Assistant version | Home Assistant OS version | Architecture | Camera model | Camera firmware | Automated tests | Yellow test | Real camera test | Result | Evidence | Unperformed tests | Known issues |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 — HACS scaffold and lifecycle | `67fae5f` | 0.1.0 | 2026.8.2 current; 2024.5.0 minimum compatibility | Not applicable locally | arm64 macOS development host; not Yellow | None | None | **Passed locally:** 6 tests on each HA version; 98.13% coverage on current; Ruff, mypy, release metadata, JSON/YAML and secret scan passed | Unperformed | Not applicable | **Automated gate passed; Yellow acceptance gate blocked/unperformed** | Local commands on 2026-08-21; no hardware evidence | HACS Action and Hassfest require published GitHub context; all ten Yellow/HACS checks | Repository is not public; no Yellow/HACS instance is connected to this workspace |
| 1 — Cloud authentication and KMS | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked by Milestone 0 gate |
| 2 — External bridge | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked by Milestone 0 gate |
| 3–8 — Embedded runtime through stable release | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked by preceding acceptance gates |

## Milestone 0 Yellow validation fields

| Field | Evidence |
|---|---|
| Home Assistant version | Unperformed |
| Home Assistant OS version | Unperformed |
| HACS version | Unperformed |
| Machine architecture | Target: AArch64; unverified |
| Install result | Unperformed |
| Setup result | Unperformed |
| Unload result | Unperformed |
| Reload result | Unperformed |
| Log result | Unperformed |

No HACS acceptance, Yellow installation, physical outage, media frame, snapshot,
or stream claim is made by this report.

## Local automated evidence — 2026-08-21

- Current runtime: Python 3.14.6, Home Assistant 2026.8.2,
  `pytest-homeassistant-custom-component` 0.13.356: `6 passed`, 98.13% branch
  coverage.
- Declared minimum: Python 3.12.13, Home Assistant 2024.5.0, historical test
  harness 0.13.119: `6 passed`. The unavailable historical `mypy-dev` lint-only
  dependency was omitted; test dependencies were installed explicitly and
  `josepy` was pinned to its historical compatible 1.14.0 release.
- `.venv/bin/ruff format --check .`: passed.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/mypy custom_components scripts`: passed, 29 source files.
- `scripts/validate_release.py`: passed for integration version 0.1.0.
- `scripts/check_secrets.py`: passed. The configured diagnostic fixtures cover
  email, password, Firebase token, UID, AuthKey, AV password, SDK key, bridge
  token, and stream path token.
- All repository JSON and workflow YAML files parsed successfully locally.

GitHub-hosted HACS Action and Hassfest jobs are defined but cannot produce
evidence until this local repository is published. Their status is therefore
unperformed, not passed.
