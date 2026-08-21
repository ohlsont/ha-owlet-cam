# Changelog

All notable changes are documented here. Versions follow semantic versioning.

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

- Local automated validation: 42 tests passed with 92.85% branch-aware coverage
  on Home Assistant 2026.8.2; Ruff and mypy pass.
- Public GitHub/HACS installation and real European account validation on the
  Yellow are explicitly deferred/unperformed. No cloud or KMS success is
  claimed against a real account yet.

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
