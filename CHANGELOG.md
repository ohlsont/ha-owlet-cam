# Changelog

All notable changes are documented here. Versions follow semantic versioning.

## Development-only local video feasibility work

- Added safe nested APK/APKM/XAPK extraction, SDK-key presence detection, and a
  dependency-free AArch64 ELF/symbol/dependency inspector.
- Added a redacted application probe and a freestanding, isolated Bionic
  `dlopen` helper; no compiled artefacts or proprietary files are committed.
- Verified a user-supplied, validly signed Owlet 3.36.0 ARM64 bundle and loaded
  all five required native libraries under a pinned AOSP Bionic runtime.
- Camera authentication, connection, frames, snapshots, and streaming remain
  unperformed; this work is not a release or a Milestone 3 gate pass.

## [0.2.0] - Unreleased

### Added

- Clean-room asynchronous Firebase email/password authentication using Home
  Assistant's shared HTTP session and Owlet Android application identity
  headers.
- European and World/US region selection, normalized camera DSNs, and redacted
  camera KMS validation.
- Typed authentication, connection, camera-not-found, rate-limit, region, and
  DSN exceptions with human-safe frontend errors.
- Native cloud-reachability, credential-availability, and authentication-expiry
  diagnostic entities backed only by coordinator-cached data.
- Reauthentication, reconfiguration, duplicate-camera protection, and grouped
  general/embedded options with one reload per successful change.
- Sanitized tests covering successful regions, HTTP failures, timeouts,
  malformed responses, refresh, flow recovery, secret leakage, and lifecycle.

### Validation status

- Local automated validation: 85 tests passed with 90.29% branch-aware coverage
  on Home Assistant 2026.8.2; Ruff, mypy, secret and release checks pass.
- A redacted real-account probe authenticated successfully against the
  user-confirmed EMEA Firebase project and reached the APK-verified regional
  KMS host. KMS returned HTTP 403 for the configured camera identifier, so no
  camera credentials were returned and the gate remains failed. Public
  GitHub/HACS installation and Yellow validation remain deferred/unperformed.
- Confirmed the identifier comes from Dream device information and the same
  account can view the camera. Raw and Bearer token formats plus APK-observed
  generic request headers all produced the same redacted KMS 403 result.
- Confirmed the account originally paired the user-reported Cam 1. EMEA Owlet
  SSO returned 200, but KMS still returned 403 after a Firebase token refresh;
  no account or camera secret was emitted.
- Completed redacted device-mapping checks: Ayla authenticated but enumerated
  zero devices; Dream account lookup succeeded without an embedded DSN, and
  its account `/devices` resource returned 404.

## [0.1.0] - Unreleased

### Added

- HACS-compatible single-integration layout with persistent `userfiles`.
- Environment-gated development config flow.
- Typed `ConfigEntry.runtime_data` lifecycle and a diagnostic status sensor.
- Secret-redacted diagnostics, translations, original brand assets, CI, and
  automated lifecycle tests.

### Validation status

- Local automated validation: 6 lifecycle/config-flow/diagnostic tests passed on
  Home Assistant 2026.8.2 and again on the declared minimum 2024.5.0; Ruff,
  mypy, metadata, JSON/YAML, and secret checks passed.
- Home Assistant Yellow/HACS gate: unperformed; this version must not be tagged
  as validated until evidence is recorded in `TEST_REPORT.md`.
