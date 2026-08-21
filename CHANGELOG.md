# Changelog

All notable changes are documented here. Versions follow semantic versioning.

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
