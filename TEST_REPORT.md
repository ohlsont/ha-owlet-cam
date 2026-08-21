# Test report

Evidence is recorded conservatively. “Passed” is used only with captured test
or real-system evidence.

| Milestone | Commit | Integration version | Home Assistant version | Home Assistant OS version | Architecture | Camera model | Camera firmware | Automated tests | Yellow test | Real camera test | Result | Evidence | Unperformed tests | Known issues |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 — HACS scaffold and lifecycle | `67fae5f` | 0.1.0 | 2026.8.2 current; 2024.5.0 minimum at that milestone | HAOS 18.2 identified through authenticated read-only HA-MCP health evidence | AArch64 Home Assistant Yellow identified; integration not installed | None | None | **Passed locally:** original 6-test lifecycle suite; later Milestone 1 suite continues to cover lifecycle | Unperformed | Not applicable | **Automated gate passed; public HACS installation deferred by user** | Local commands and read-only system-health evidence on 2026-08-21 | HACS Action, Hassfest in GitHub context, and the ten physical install/lifecycle/log checks | Public repository intentionally deferred until core functionality works |
| 1 — Cloud authentication and KMS | `1e6a256` | 0.2.0 | 2026.8.2 current; 2024.11.0 minimum | HAOS 18.2 target identified; integration not installed | AArch64 Yellow target; tests executed on arm64 macOS | None | None | **Passed locally:** 42 tests and 92.85% coverage on current; 42 tests and 93.10% on minimum; Ruff, mypy, metadata, JSON/YAML and secret scan passed | Unperformed | Unperformed | **Automated implementation passed; real-account gate unperformed** | Sanitized fixtures cover Europe, World/US, invalid credentials/DSN, KMS 401/403/404, rate limits, server errors, timeout, malformed JSON, refresh, duplicates, reauth/reconfigure/options and secret leakage | Real European login/KMS lookup, diagnostics/log search, wrong-password correction on Yellow | User deferred publication/manual installation; no real account or camera credential was used |
| 2 — External bridge | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked by Milestone 0 gate |
| 3–8 — Embedded runtime through stable release | `probe/local-video` working tree | 0.2.0 base; no embedded release | Not applicable to local spike | Not applicable to local spike | ARM64 macOS host; Linux/ARM64 Docker target | None supplied | None supplied | **Partial feasibility evidence:** 15 archive/ELF tests; full suite 57 passed at 90.01% coverage | Unperformed | Unperformed | **Out-of-order feasibility spike only; no embedded gate passed** | Local commands on 2026-08-21; exact results below | User APK extraction, Bionic `dlopen`, KMS handoff, camera connection, frames, FFprobe, Yellow runtime | User explicitly prioritized proving real local video before Home Assistant installation; previous stable work remains on `build/milestone-1` |

## Milestone 0 Yellow validation fields

| Field | Evidence |
|---|---|
| Home Assistant version | Core 2026.8.2 identified through authenticated read-only HA-MCP system health; integration test unperformed |
| Home Assistant OS version | 18.2 identified through authenticated read-only HA-MCP system health |
| HACS version | 2.0.5 identified through authenticated read-only HA-MCP system health |
| Machine architecture | AArch64, board Yellow, identified through authenticated read-only HA-MCP system health |
| Install result | Unperformed |
| Setup result | Unperformed |
| Unload result | Unperformed |
| Reload result | Unperformed |
| Log result | Unperformed |

No HACS acceptance, Yellow installation, physical outage, media frame, snapshot,
or stream claim is made by this report.

## Local video feasibility spike — 2026-08-21

- The exact `btoth525/Owlet-To-Rtsp` image corresponding to commit `132620a`
  was inspected and its pinned `linux/amd64` image booted successfully under
  OrbStack emulation on the ARM64 Mac. The control panel returned HTTP on a
  loopback-only port. No Owlet account, APK, camera credential, or frame was
  supplied to it.
- That external bridge was rejected as the real-camera test harness because its
  current implementation persists the account password and logs partial token,
  UID, AuthKey, and AV-password values. `jquick/owlet-go` was also rejected
  because its documented setup requires MITM certificate installation and its
  current stream log prints the full UID. Neither repository has a licence file,
  and no implementation source was copied.
- Clean-room APK safety and ELF inspection prerequisites were implemented on the
  separate `probe/local-video` branch. Focused validation: `15 passed`. Full
  validation: Ruff passed, mypy passed for 25 source files, `57 passed` with
  90.01% branch-aware coverage, secret scan passed for 66 files, and release
  metadata remained valid for 0.2.0.
- No user-supplied Owlet APK/APKM/XAPK is present in
  `custom_components/owlet_cam/userfiles/uploads/`. Library compatibility,
  native loading, camera connection, H.264 receipt, and FFprobe therefore remain
  unperformed.

## Milestone 1 local automated evidence — 2026-08-21

- Python 3.14.6 and Home Assistant 2026.8.2: `42 passed`, 92.85%
  branch-aware coverage.
- Python 3.12.13, Home Assistant 2024.11.0, historical test harness 0.13.181,
  `josepy==1.14.0`, and `pycares==4.4.0`: `42 passed`, 93.10% coverage. The
  compatibility pins prevent unrelated modern transitive packages from
  breaking the historical Home Assistant test environment.
- Both configured Firebase regions, Android identity headers, KMS credential
  presence reduction, token refresh, typed safe failures, DSN O/0 handling,
  flow recovery, duplicate protection, reauth, reconfigure, grouped options,
  setup retry/auth failure, unload/reload and entity property isolation are
  covered by sanitized tests.
- No real Owlet account request, KMS response, camera credential, frame, or
  media evidence has been collected.
- `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, and
  `.venv/bin/mypy custom_components scripts`: passed.
- `scripts/validate_release.py`, `scripts/check_secrets.py`, repository JSON,
  and workflow YAML validation: passed for version 0.2.0.

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
