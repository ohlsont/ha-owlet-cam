# Changelog

All notable changes are documented here. Versions follow semantic versioning.

## [0.9.1] - 2026-08-27

### Added

- Opt-in embedded temperature, humidity, sound-level, illuminance and Wi-Fi
  signal entities. Telemetry stays on the existing native camera session and
  reaches Home Assistant through a dedicated inherited binary pipe.
- Bounded value validation, cached diagnostics, helper-pipe supervision and
  tests proving that malformed or failed telemetry publication cannot stop
  H.264 video.

### Validation status

- The complete 292-test suite passes at 85.22% branch-aware coverage; Ruff,
  mypy, three helper compilation modes and reproducible AArch64 helper packaging
  pass.
- A checksum-verified Yellow deployment on Core 2026.8.3 produced real sound
  (`0 dB`), illuminance (`17 lx`) and Wi-Fi (`-49 dBm`) readings while the same
  bounded session retained H.264 and AAC. Temperature and humidity remained
  unknown on the tested Owlet Cam 1 and are not claimed as real-device-validated.

## [0.8.0] - Unreleased

### Added

- A credential-free desktop APKPure preparation path. It requests only the
  ARM64 Dream bundle through apkeep and produces the same compact private
  `.owletcam` package without requiring Android, Google, or Owlet credentials.
- Embedded experimental mode is now presented first and selected by default;
  external bridge mode remains supported as the separate-host compatibility
  fallback.
- Optional incoming AAC-LC audio for embedded live streams. The isolated native
  helper drains ThroughTek's audio FIFO into a separate inherited pipe, and the
  integration adds 8 kHz mono AAC to the loopback MPEG-TS without transcoding.
- Cached audio status, codec, frame counters and safe error codes in diagnostic
  entities and downloadable diagnostics.

### Safety

- APKPure preparation fails closed unless all five executable native-library
  hashes match the set independently observed in a signed APKPure Dream bundle
  and an official Google Play Dream installation. Unknown store updates direct
  the user to ADB or the authenticated Google Play path instead of executing
  unreviewed native code.
- Audio is enabled by default after successful real Owlet Cam 1 / Yellow
  validation and can be disabled for video-only operation. Unsupported codecs,
  malformed audio frames and audio-pipe failures are isolated from the H.264
  producer so video can continue in a bounded video-only fallback mode.

### Validation status

- Python packetizer, separate-pipe supervision, malformed-audio fallback and
  strict FFprobe parsing are covered by automated tests. On Home Assistant
  Yellow, a real Owlet Cam 1 supplied native ADTS AAC-LC; Core-local FFprobe
  decoded H.264 plus 8 kHz mono AAC and counted both tracks. The user then
  confirmed audible room audio in Home Assistant's live camera view.
- Added bounded, allowlisted FFprobe observations and stable parse error codes.
  These exposed and corrected the camera's public `0x88` codec-label/framing
  mismatch without retaining URLs, paths, stderr, tags, or media bytes.

## [0.7.0] - Unreleased

### Added

- Native external-bridge camera, metric room sensors, health entities,
  multi-camera selection, reauthentication, reconfiguration, and grouped
  options against the observed `btoth525/Owlet-To-Rtsp` HTTP API.
- Checksum-pinned, exact-version AArch64 helper release downloads with bounded
  disk streaming, atomic installation, cleanup, and actionable Repairs.
- Reproducible helper release builds, archive inspection, checksums, SPDX SBOM,
  licence manifest, changelog-derived notes, and Home Assistant beta CI.
- The administrator upload/runtime panel and the previously validated embedded
  snapshot and live H.264 paths from Milestones 3 through 7.
- A deterministic desktop runtime preparer that minimizes a user-owned Owlet
  application into a strict `.owletcam` package, with existing-archive, adb and
  optional token-file-only apkeep acquisition paths.
- Native Home Assistant `.owletcam` file-selection during embedded setup and an
  optional replacement/deletion step during Reconfigure. The permanent custom
  runtime sidebar panel and its private HTTP API were removed; runtime actions
  remain disabled-by-default diagnostic device buttons.

### Security

- External bridge credential fields returned by the bridge are ignored and are
  never represented by the adapter's typed models.
- Release inspection rejects Owlet/ThroughTek libraries, application packages,
  unapproved shared libraries, traversal paths, special members, and common
  serialized secret patterns.
- Compact runtime packages accept exactly five named ARM64 libraries, one
  private SDK-key member and one integrity manifest; unexpected members,
  duplicate paths, unsupported package IDs and hash/size mismatches are rejected.

### Validation status

- Deployed commit `e75ab86` to Home Assistant Yellow on Core 2026.8.3 / HAOS
  18.2. The configuration check and restart succeeded, the entry loaded, and
  the former runtime sidebar panel was absent from the live panel registry.
- Installed the exact inspected AArch64 helper artifact from successful CI run
  `32956581716` using its independently matched SHA-256 and an atomic fixed-
  allowlist swap. Runtime revalidation returned `ready` with helper 0.7.0, five
  compatible libraries, all child processes reaped, no active Repairs and no
  current structured Owlet system-log entries.
- Removed deployment staging, rollback and obsolete helper backups after the
  gate passed, retained the active runtime and user-supplied proprietary files,
  and fully closed the temporary key-only SSH port. This is private manual-
  deployment evidence, not HACS installation or stable-release evidence.

## Development-only local video feasibility work

- Added safe nested APK/APKM/XAPK extraction, SDK-key presence detection, and a
  dependency-free AArch64 ELF/symbol/dependency inspector.
- Added a redacted application probe and a freestanding, isolated Bionic
  `dlopen` helper; no compiled artefacts or proprietary files are committed.
- Verified user-supplied, validly signed Owlet 3.36.0 and 3.40.0 ARM64 bundles;
  their five required native libraries are identical and load under a pinned
  AOSP Bionic runtime.
- Added redacted authorized Firestore camera discovery, revealing that Dream's
  visible camera identifier differs from the internal KMS DSN for this account.
- Added a clean-room, stdin-secret-only AArch64 connection/frame helper and a
  local runner that removes its emulator files after each probe.
- Received 100 real H.264 frames in each of three separate ARM64 emulator probes
  with SPS/PPS/IDR present, parsed 1920×1080, and clean shutdown. This is local
  feasibility evidence, not a Home Assistant/Yellow or release gate pass.
- Confirmed by user observation that Dream's Android live view worked after the
  helper probes, providing evidence of clean camera-session release.
- Moved authorized Firestore serial-to-KMS discovery into the production cloud
  client; the Home Assistant flow now accepts the app-visible camera serial
  while keeping the different internal KMS identifier in memory only.
- Added a supervised process-group runner, strict helper response schemas,
  runtime checksum manifests, atomic safe archive installation, config-entry
  unload termination, cached diagnostics, and disabled-by-default runtime and
  frame-probe buttons.
- Added a deterministic proprietary-free runtime packager. A newly compiled
  clean-room helper build loaded all five user libraries and received 100 real
  H.264 frames under the ARM64 emulator before packaging.
- Verified the packaged helper's exact explicit-Bionic-linker launch shape in a
  read-only ARM64 Linux container and use only a fixed, non-secret
  `LD_LIBRARY_PATH`; camera secrets remain stdin-only.
- A private Yellow installation loaded successfully and completed real EMEA
  cloud authentication, authorized camera discovery, KMS validation, entity
  setup, config-entry reload, and redacted diagnostics.
- The first Yellow runtime probe exposed a memory defect: nested APKs were held
  in `BytesIO`, and Supervisor recorded Core plus Matter exits with code 137.
  Nested APKs now spool to mode-0600 disk files, and only previous-process
  extraction directories are cleaned on retry. One corrected press caused no
  new Core exit but overlapped a still-completing config-entry reload, which
  replaced the runtime manager before a result was retained. The attempt is
  inconclusive. A later reload-settled Yellow probe completed in about 19
  seconds, loaded all five required user libraries, reported zero failures, and
  left Core running without a new exit or Repair. Entry unload/re-enable and
  restart recovered cleanly, so the Yellow native capability gate is passed.
- Current automated validation: 125 tests passed at 86.49% branch-aware
  coverage; Ruff and mypy passed.
- Three bounded Yellow probes each received 100 real H.264 frames with seven
  SPS, seven PPS, seven IDR units, parsed 1920×1080, 13.599–14.341 estimated
  FPS, 71–262 ms to first frame, and clean shutdown. Core remained running with
  no new exit, Repair, or Owlet error.
- The user confirmed Dream live video worked after the Yellow probes, providing
  evidence that the official app reclaimed the camera after helper teardown.
- Added strict `lan`/`p2p`/`relay` session-mode reporting to the clean-room
  helper. The rebuilt AArch64 binary and runtime archive passed local ELF,
  safe-error, checksum and atomic-install validation, then were
  checksum-verified and atomically deployed on Yellow.
- A Dream-open Yellow probe received 100 valid H.264 frames at 640×360 in `lan`
  mode; after Dream closed, a second probe immediately reacquired 100 frames at
  1920×1080 in `lan` mode. Both had SPS/PPS/IDR and clean shutdown. Direct
  process-list checks after the runtime probe and both frame probes found no
  orphan helper, completing the Milestone 4 bounded frame-probe gate.
- RTSP/live streaming, Dream uninterrupted-view, and physical outage
  validation remain unperformed.
- Implemented the local Milestone 5 snapshot path: a separate clean-room helper
  writes one decodable SPS/PPS/IDR access unit only through an inherited file
  descriptor; the integration keeps the temporary H.264 file mode 0600, decodes
  it with Home Assistant's pinned FFmpeg component, validates JPEG framing,
  caches briefly, serializes concurrent requests, and cancels work on unload.
- Added a snapshot-only camera entity with zero stream feature flags plus tests
  for capture protocol strictness, inherited descriptors, invalid output,
  decode timeout, concurrent callers, caching, cleanup, shutdown races and
  secret-free FFmpeg arguments.
- Deployed the checksum-verified helper 0.5.0-dev runtime on Yellow. Home
  Assistant displayed real 1920×1080 and 864×480 JPEGs; ten sequential calls,
  two simultaneous callers and the standard `camera.snapshot` service passed.
- Repeated cache-expired test captures reached Owlet's KMS rate limit and
  exposed a stuck runtime status. The correction maps typed cloud and decode
  failures to redacted safe codes, cleans temporary files, and leaves the
  validated snapshot path retryable. Regression coverage includes rate-limit,
  authentication, connection, camera-not-found and decode-timeout failures.
- Completed the Milestone 5 Yellow gate: the user confirmed Dream reclaimed
  live video; simultaneous in-app-browser and Chrome clients both displayed the
  camera after a concurrent reload; and a 30-minute periodic dashboard-snapshot
  soak reduced Core memory from 815,271,936 to 801,710,080 bytes. Zero Repairs
  and no new Owlet system-log entry were present afterward.
- Deleted the verified `camera.snapshot` test artefact from Yellow and the Mac.
  Direct Core-PID orphan enumeration remains explicitly unperformed because the
  supported SSH add-on lacks that namespace; no host PID, Docker, privileged or
  security-weakening workaround was used.
- Added a fourth isolated helper mode that keeps one TUTK session open and sends
  length-framed Annex-B H.264 through stdout while reserving stderr for bounded,
  redacted lifecycle events. Secrets still arrive only through startup stdin.
- Added one integration-managed loopback media source with first-viewer start,
  one producer/many consumers, SPS/PPS/IDR gating, reconnect bounds, configurable
  idle shutdown, keep-warm support and config-entry teardown.
- Rejected the initial raw-H.264 HTTP transport after Home Assistant's stream
  worker reported seven consecutive packets without DTS. Replaced it with an
  independently implemented, timestamped single-program MPEG-TS packetizer
  carrying copied H.264 over `127.0.0.1`; no private go2rtc process, global
  configuration change or video transcode is used.
- Corrected the private Yellow deploy script so rollback directories live
  outside `custom_components`; Home Assistant had treated a dot-prefixed backup
  manifest as another integration and raised an import error.
- Validated the corrected path on Yellow with changing real infrared frames in
  two simultaneous Home Assistant viewers, reconnect after idle, a valid
  `camera.snapshot` JPEG, and a playable five-second `camera.record` MP4. Live
  diagnostics showed one producer, two consumers, healthy media, and zero
  reconnects; the final settled state was idle with zero consumers.
- Reload while two viewers were active initially waited for Home Assistant's
  retained media consumer. Added private prior-validation consent state so
  settled reloads and restarts rerun every native safety gate automatically
  without a second button press. Cold-start recovery waits for Home Assistant's
  public startup-complete event; this passed on Yellow.
- Corrected config-entry unload ordering so forwarded platforms unload before
  runtime shutdown, and cancel any startup-waiting recovery task on unload.
- Corrected one-shot startup-listener cleanup after a Yellow log check caught a
  duplicate remove attempt; the final cold restart recovered automatically with
  no Owlet system-log entry and zero active Repairs.
- Corrected active-viewer unload for Python 3.14: the loopback server closes and
  bounds tracked client tasks before waiting for the listening server, and the
  camera entity stops Home Assistant's public stream worker before removing the
  integration-owned source. A Yellow reload with real video open returned in
  4.318 seconds, recovered automatically, emitted no Owlet, demuxing or
  connection-refused system-log entry, and displayed fresh real video after the
  retained dialog was closed and reopened. Idle teardown subsequently passed.
  Direct Core-namespace FFprobe, two-hour/overnight soaks, companion app and
  physical outage tests remained unperformed at this point; the later revised
  acceptance decision is recorded below.
- Current automated validation: 163 tests passed at 86.53% branch-aware
  coverage; Ruff and mypy passed. Two independent ARM64 helper builds produced
  the same proprietary-free archive.
- Added a disabled-by-default Core-local media probe that invokes Home
  Assistant's sibling FFprobe with bounded duration/output and reduces stderr
  to redacted error codes. Yellow reported H.264 Baseline level 4.0,
  1920×1080, 15 FPS, 708.3 kbit/s, 124 counted frames and MPEG-TS.
- Corrected the probe's first-consumer gate: the temporary
  `stream_probe_running` status no longer rejects the probe's own loopback
  connection after all native capability checks have passed.
- A final clean-log run exposed one timestamp discontinuity when a new producer
  inherited an old cached GOP and wall-clock origin after idle. New native
  sessions now clear cached media and reset transport timestamps while keeping
  the loopback URL stable. After restart, live → idle → live displayed real
  video, reached final idle with zero consumers/reconnects, and produced zero
  matching system-log entries or Repairs.
- Current automated validation: 190 tests passed at 86.06% branch-aware
  coverage; Ruff, mypy, secret scan and release validation passed.
- Recorded a shortened Yellow continuous-view test: 7 minutes 44.65 seconds,
  6,878 additional aggregate frames, zero reconnects, normal idle teardown,
  zero matching Owlet system-log entries and zero active Repairs. The formal
  two-hour and overnight soaks remain explicitly unperformed.
- Added redacted stream interruption/recovery timestamps and safe error codes,
  session/stop counters, and helper started/reaped/all-reaped/forced-kill
  diagnostics. Unexpected interruptions now leave a fixed-code warning without
  exposing secrets. The freestanding ARM64 helper requests Linux parent-death
  termination before reading credentials.
- Rebuilt and checksum-verified the proprietary-free ARM64 helper on Yellow.
  Automatic native validation reached `ready`; a real bounded stream delivered
  863 frames with zero reconnects and then stopped with started 2/reaped 2, all
  reaped, zero forced kills, zero current Owlet system-log entries and zero
  active Repairs.
- Milestone 6 is accepted under the user's revised validation scope. Formal
  two-hour/overnight, Companion-app, Dream-coexistence, physical-outage and
  additional reboot tests were explicitly waived and remain unperformed.
- Implemented the Milestone 7 administrator-only Home Assistant runtime panel
  and same-origin authenticated API. APK/APKM/XAPK/ZIP bodies stream to disk in
  bounded chunks, use generated private filenames, expose upload progress, and
  reject unsupported, oversized, empty, partial or symlink-directed uploads.
- Added safe application package/version detection, private persisted SDK-key
  recovery, verified-library names and hashes, ABI and secret-presence booleans,
  runtime/stream counters, and coordinator facts to redacted diagnostics. No
  paths, PIDs, media tokens or credential values are returned.
- Uploaded archives are deleted after a successful extraction probe by default;
  an explicit option retains them. A confirmation-gated admin action stops the
  producer and deletes uploaded applications, extracted proprietary libraries,
  the SDK key, temporary material and validation state while preserving the
  open-source helper runtime.
- Added actionable auto-resolving Repairs for missing/invalid applications,
  missing ARM64 splits/libraries/SDK keys, unsafe storage, incompatible native
  libraries, missing/invalid/checksum-failed/obsolete helper runtimes,
  reauthentication and repeated stream recovery failure.
- Added disabled-by-default authentication-test and restart-stream entities plus
  corresponding bounded panel controls. The panel also exposes the existing
  runtime, frame and Core-local stream probes.
- Current Milestone 7 local validation: 228 tests passed at 85.14%
  branch-aware coverage. Ruff, mypy, JSON validation, JavaScript syntax,
  release validation, secret scan and diff whitespace checks passed.
- Deployed the checksum-verified panel source to Yellow on Core 2026.8.3 / HAOS
  18.2. The administrator sidebar panel rendered successfully, the persisted
  proprietary bundle recovered without its uploaded archive, five AArch64
  libraries and the SDK-key presence gate passed, a real 100-frame probe
  returned 1920×1080 at 10.632 FPS, and Core-local FFprobe reported H.264
  Baseline 1920×1080 at 15 FPS and 762.7 kbit/s.
- A config-entry reload exposed an intermittent no-input helper race: the probe
  could exit before asyncio drained an empty stdin write. The runner now skips
  the write/drain when no payload exists, with a deterministic regression test;
  the exact corrected file is checksum-installed on Yellow. A post-fix Core
  restart automatically returned the runtime to `ready`: all five libraries
  were compatible, no safe error was present, helper accounting was started
  1/reaped 1 with zero forced kills, active Repairs were empty, and the current
  structured Owlet log was empty.
- Completed the real Yellow panel lifecycle: the confirmation-gated delete
  removed all proprietary material and created the expected missing-application
  Repair; the panel then accepted a user-selected 154,946,466-byte XAPK and
  cleared the Repair. A bounded runtime probe extracted the package, deleted
  the uploaded archive by default, restored the SDK-key presence gate and all
  five AArch64 libraries, returned `ready`, reaped all helper children, and left
  zero active Repairs or current Owlet system-log entries. The Milestone 7 gate
  is accepted.

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

- Local automated validation: 92 tests passed with 90.29% branch-aware coverage
  on Home Assistant 2026.8.2; Ruff, mypy, secret and release checks pass.
- A redacted real-account probe authenticated successfully against the
  user-confirmed EMEA Firebase project. Direct authorized Firestore references
  resolved the account's internal camera DSN, and regional KMS validation then
  returned true UID/AuthKey/AV-password presence booleans without values.
  Public GitHub/HACS installation and Yellow validation remain unperformed.
- Confirmed the identifier comes from Dream device information and the same
  account can view the camera. Raw and Bearer token formats plus APK-observed
  generic request headers all produced the same redacted KMS 403 result.
- Confirmed the account originally paired the user-reported Cam 1. EMEA Owlet
  SSO returned 200, but KMS still returned 403 after a Firebase token refresh;
  no account or camera secret was emitted.
- Earlier legacy/Ayla mapping checks did not reveal the camera. The working
  path follows Dream's authorized Firestore account → service → device
  references; the printed identifier is not the internal KMS DSN.

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
