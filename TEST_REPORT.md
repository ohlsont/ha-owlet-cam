# Test report

Evidence is recorded conservatively. “Passed” is used only with captured test
or real-system evidence.

| Milestone | Commit | Integration version | Home Assistant version | Home Assistant OS version | Architecture | Camera model | Camera firmware | Automated tests | Yellow test | Real camera test | Result | Evidence | Unperformed tests | Known issues |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 — HACS scaffold and lifecycle | `67fae5f` | 0.1.0 | 2026.8.2 current; 2024.5.0 minimum at that milestone | HAOS 18.2 identified through authenticated read-only HA-MCP health evidence | AArch64 Home Assistant Yellow identified; integration not installed | None | None | **Passed locally:** original 6-test lifecycle suite; later Milestone 1 suite continues to cover lifecycle | Unperformed | Not applicable | **Automated gate passed; public HACS installation deferred by user** | Local commands and read-only system-health evidence on 2026-08-21 | HACS Action, Hassfest in GitHub context, and the ten physical install/lifecycle/log checks | Public repository intentionally deferred until core functionality works |
| 1 — Cloud authentication and KMS | `probe/local-video` working tree | 0.2.0 | 2026.8.2 current; 2024.11.0 minimum | HAOS 18.2 target identified; integration not installed | AArch64 Yellow target; tests executed on arm64 macOS | Not established | Not established | **Passed locally:** 85 tests at 90.29% branch-aware coverage; Ruff, mypy, secret and release checks passed | Unperformed | Unperformed | **EMEA authentication passed locally; KMS gate failed with HTTP 403** | The exact identifier was confirmed from Dream device information and the same account can view its stream. The clean-room probe authenticated with the signed Dream app identity and reached `camera-kms.eu.owletdata.com`; raw-token, Bearer-token, and APK-observed generic-header trials all returned 403 without camera credentials | Successful KMS lookup, diagnostics/log search, wrong-password correction on Yellow, camera connection and all media tests | KMS denies this account/device combination despite the official app having access; account ownership/entitlement or a server-side device mapping remains unresolved |
| 2 — External bridge | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked by Milestone 0 gate |
| 3–8 — Embedded runtime through stable release | `probe/local-video` working tree | 0.2.0 base; no embedded release | Not applicable to local spike | Not applicable to local spike | ARM64 macOS host; Linux/ARM64 Docker target | Not established | Not established | **Partial feasibility evidence:** 17 focused archive/ELF tests; full suite 85 passed at 90.29% coverage; Ruff, mypy, release and secret checks passed | Unperformed | Unperformed | **Local extraction and Bionic load sub-gates passed; no embedded milestone gate passed** | Local commands on 2026-08-21; exact redacted results below | Successful KMS handoff, camera connection, frames, FFprobe, in-Core Yellow runtime/lifecycle | User explicitly prioritized proving real local video before Home Assistant installation; previous stable work remains on `build/milestone-1` |

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
  separate `probe/local-video` branch. Current focused validation: `17 passed`.
  Full validation: Ruff passed, mypy passed for 31 source files, `85 passed` with
  90.29% branch-aware coverage, secret scan passed for 72 release-source files,
  and release metadata remained valid for 0.2.0 while correctly excluding the
  Git-ignored persistent runtime directory.
- apkeep 1.0.0 for ARM64 was downloaded from EFF's GitHub release. Its SHA-256
  matched the release API, and its detached signature verified with EFF-hosted
  key fingerprint `1073 E74E B38B D6D1 9476 CBF8 EA9D BF9F B761 A677`.
  The APKPure backend was used without Google or Owlet credentials.
- The ignored application bundle is package `com.owletcare.sleep`, version
  3.36.0 (`62726`), ARM64, outer SHA-256
  `93889a94b6d7e95551d0ab295b26aa786aea98c347365c83fd202f5c3c036c55`.
  All four nested APKs passed Android signature verification and shared signer
  SHA-1 `2a3bc26db0b8b0792dbe28e6ffdc2598f9b12b74`, consistent with independent
  current and historical store metadata. APKPure offered no newer ARM64 version
  through apkeep at the time of testing; newer store versions were not tested.
- Safe extraction found the SDK-key pattern without printing its value and found
  the five allowlisted libraries. Every library was 64-bit little-endian
  AArch64, had all required defined symbols, and had no writable-executable load
  segment. Library SHA-256 values: `libAVAPIs.so`
  `9aebb5557966218798b1a43af2f623c48116f73f9bbee65214ca2af264bd022b`,
  `libIOTCAPIs.so`
  `3fbfc08b8fe67c1fb2495af0d0d5871d5e3b2a9207fe104284baaf8416d1bada`,
  `libP2PTunnelAPIs.so`
  `771a424d3ae77dd1c265fcf34a933bfaebb14e2ffe990f4c24ead8e9d1c6e40e`,
  `libRDTAPIs.so`
  `3d0da6449c9417b5f60f13119c6927be6c12ea6591ad7997324ec77e96d7c27f`,
  and `libTUTKGlobalAPIs.so`
  `67e9eca19b730cec70178a38b1d5e265a4a00b28127d941696f133af879f4593`.
- The no-camera glibc load probe failed for all five libraries with
  `libc.so: invalid ELF header`, confirming that the Android libraries require
  Bionic. This was an expected compatibility observation, not a camera failure.
- A pinned open-source AOSP ARM64 runtime APEX (commit `070571b4`, SHA-256
  `83bf0dce249728dae48149b80d28b48115c54adad95a352120d58a6ac669d1fc`)
  resolved every dependency. A freestanding AArch64 PIE helper then called
  `dlopen` and `dlclose` for all five libraries in a network-disabled container;
  five `library_probe` responses and `probe_complete` all returned `ok: true`.
  No SDK key, cloud token, KMS value, account credential, or camera session was
  supplied to the process.
- Camera authentication/KMS handoff, native camera connection, H.264 receipt,
  FFprobe, subprocess supervision inside Home Assistant Core, and Yellow
  lifecycle validation remain unperformed. No video claim is made.

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
- A local `.env` was excluded from Git, restricted to mode `0600`, set to the
  user-confirmed Europe region, and read without
  exporting values into the process environment, and never printed. The signed
  Dream 3.36.0 APK established package `com.owletcare.sleep`, signer SHA-1, and
  the World/US and Europe Firebase Auth project identities. Androguard was used
  only for public application-configuration observations; its temporary output
  and generated log/database were not retained in the repository.
- The user confirmed that the same typed credentials successfully log into the
  Dream iPhone app with EMEA selected. The clean-room probe then used the signed
  Dream Android identity, public EMEA Firebase application ID, and Firebase v1
  password endpoint. Authentication succeeded without exposing the returned
  token. Static APK inspection established the `.eu` KMS hostname suffix; the
  corrected request reached that host and returned HTTP 403 for the configured
  camera identifier. No UID, AuthKey, AV password, SDK key, full email,
  password, token, or camera identifier was emitted.
- The user then confirmed that the configured identifier is the exact value in
  Dream's device-information screen and that this same account can view the
  camera. Narrow static inspection showed that Dream passes its internal `dsn`
  unchanged to the EMEA KMS lookup with a fresh Firebase token. The APK adds no
  KMS-specific App Check or secondary authorization value. Raw-token,
  Bearer-token, and app/version user-agent plus `Accept-Language` trials all
  returned the same safe result: HTTP 403 `camera_forbidden`.
- **Acceptance gate: failed at KMS.** Real EMEA authentication is now proven
  locally, but camera metadata lookup did not succeed. Native camera connection
  and frame work must not begin. The unresolved boundary is server-side
  authorization/device mapping or whether this login is the primary camera
  owner rather than a shared caregiver account.
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
