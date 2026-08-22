# Test report

Evidence is recorded conservatively. “Passed” is used only with captured test
or real-system evidence.

| Milestone | Commit | Integration version | Home Assistant version | Home Assistant OS version | Architecture | Camera model | Camera firmware | Automated tests | Yellow test | Real camera test | Result | Evidence | Unperformed tests | Known issues |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 — HACS scaffold and lifecycle | `67fae5f` | 0.1.0 | 2026.8.2 current; 2024.5.0 minimum at that milestone | HAOS 18.2 | AArch64 Home Assistant Yellow; private manual install | None | None | **Passed locally:** original 6-test lifecycle suite; later suites continue to cover lifecycle | **Partial:** manual setup, reload, unload, re-enable, restart, entity removal/restoration, and clean Owlet logs passed | Not applicable | **Lifecycle gate passed; HACS-installation gate deferred by user** | Local tests plus authenticated HA-MCP lifecycle evidence on 2026-08-22 | HACS custom-repository acceptance, HACS Action and Hassfest in GitHub context | Public repository intentionally deferred until core functionality works |
| 1 — Cloud authentication and KMS | `probe/local-video` working tree | 0.2.0 | 2026.8.2 current; 2024.11.0 minimum | HAOS 18.2 | AArch64 Yellow | Owlet Cam 1, user-reported; not hardware-verified | Not established | **Passed locally:** current full suite 125 tests at 86.49% branch-aware coverage; Ruff and mypy passed | **Partial:** manual install, setup, reload, entities, cloud/KMS, and redacted diagnostics passed | **Passed on Yellow:** EMEA authentication, authorized camera discovery, and KMS credential-presence validation | **Cloud/KMS Yellow core path passed; full Milestone 1 gate incomplete** | Loaded config entry; cloud and credential booleans on; diagnostics redacted email, password and camera identifier | HACS installation and wrong-password reauthentication correction | The app-visible serial differs from the internal KMS DSN; the production client resolves this relationship while keeping the internal value in memory only |
| 2 — External bridge | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked by Milestone 0 gate |
| 3 — Embedded ARM64 runtime probe | `probe/local-video` working tree | 0.2.0 base; helper 0.4.0-dev; no embedded release | Core 2026.8.2 | HAOS 18.2 | Yellow AArch64; ARM64 macOS/Docker/emulator local targets | Owlet Cam 1, user-reported | Not established | **Passed locally:** full suite 125 passed at 86.49% coverage; Ruff and mypy passed | **Passed native capability gate after correction:** runtime `ready`, all five required libraries loaded, unload/re-enable and restart recovered cleanly | No-camera library probe passed on Yellow; no camera connection attempted | **Yellow native runtime gate passed; release-distribution checks remain** | Helper 0.4.0-dev, compatibility `true`, no safe error, Core `RUNNING`, zero Repairs, no new code-137 exit, clean entry unload/re-enable/restart | HACS release asset download, direct `ps` orphan capture, separate `probe_runtime` command, detected APK version reporting, GitHub release build | Initial in-memory extraction caused code 137; disk-spooling correction passed. Restart was unusually slow and the user performed an additional manual restart; final setup was clean |
| 4 — Embedded connection and frame probe | `probe/local-video` working tree | Development-only; no embedded release | Not applicable to local spike | Not applicable to local spike | Android 15 ARM64 emulator on ARM64 macOS | Owlet Cam 1, user-reported | Not established | Full 122-test suite at 86.47% coverage, Ruff, and mypy passed | Unperformed | **Passed locally:** required repeated 100-frame H.264 probes, newly rebuilt-helper confirmation, and Dream recovery | **Local real-frame and session-release sub-gates passed; Yellow gate unperformed** | Exact redacted statistics are recorded below; every run contained SPS, PPS and IDR NALs, parsed 1920×1080, and reported clean shutdown; user confirmed working Dream video after the probes | Yellow execution, session-mode observation, enabled Home Assistant controls, and official-app-open-before-probe behavior | Docker/OrbStack IOTC timed out with `-13`; the same helper connected under the emulator's native Bionic/network environment, so Docker network compatibility remains unresolved |
| 5–8 — Snapshot through stable release | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked until the complete Milestone 4 acceptance gate passes |

## Milestone 0 Yellow validation fields

| Field | Evidence |
|---|---|
| Home Assistant version | Core 2026.8.2 |
| Home Assistant OS version | 18.2 |
| HACS version | 2.0.5; custom-repository installation unperformed |
| Machine architecture | AArch64, board Yellow |
| Install result | Private manual installation succeeded; HACS installation unperformed |
| Setup result | Entry reached `loaded`; diagnostic entities appeared |
| Unload result | Entry reached `not_loaded`; runtime entity disappeared |
| Reload result | Config-entry reload, re-enable, and restart restored `loaded` without duplicate entities observed |
| Log result | Only Home Assistant's standard unverified-custom-integration warning; no Owlet exception/warning |

No HACS acceptance, Yellow installation, physical outage, Home Assistant camera,
snapshot, RTSP, or live-dashboard stream claim is made by this report. The only
media claim is the isolated local frame-probe evidence recorded below.

## Yellow live validation — 2026-08-22

- Home Assistant MCP configured Terminal & SSH temporarily with one ED25519
  public key, an empty password, TCP forwarding disabled, and LAN port 22222.
  The integration/runtime archive and separate user-supplied application were
  transferred to the user's own Yellow. Both remote SHA-256 values matched the
  local originals. MCP then removed the key and port mapping, restarted the app,
  and confirmed zero authorized keys, no password, TCP forwarding false, and a
  null SSH port. A LAN connection check confirmed the port was closed.
- Home Assistant's configuration check was valid before restart. Core 2026.8.2
  restarted without an Owlet import error and reached `RUNNING`. The manually
  installed `owlet_cam` entry reached `loaded`; a config-entry-only reload
  succeeded without a full restart.
- Real EMEA authentication, authorized Firestore camera discovery, and regional
  KMS validation succeeded inside Home Assistant Core on Yellow. Eleven enabled
  diagnostic entities appeared. Cloud reachable and credential presence were
  on. Serialized diagnostics redacted email, password, and camera identifier and
  exposed only safe booleans/timestamps; no runtime secret was present.
- The disabled-by-default runtime button was enabled for a no-camera probe. The
  MCP connection dropped during the service call. Supervisor later recorded
  Core exiting with code 137 at 13:14:28 and restarting automatically; Matter
  Server also exited 137 twice in the same interval. The recorder reported an
  unclean shutdown. No native probe success response exists, so the runtime gate
  failed. Core recovered to `RUNNING`, the cloud entry returned to `loaded`, and
  the probe button was disabled again.
- Inspection found the 148 MiB nested application split was copied into
  `BytesIO` by the original extractor. The implementation now streams nested
  APKs into mode-0600 temporary files and assigns extraction directories a
  per-Core-process session, cleaning only previous-process remnants. The real
  package completed the corrected local extraction in 1.58 seconds. Automated
  validation after both fixes: 125 tests, 86.49% branch-aware coverage, Ruff,
  mypy, secret scan, release validation, and diff whitespace checks all passed.
- Both corrected source files were transferred and checksum-verified on Yellow,
  SSH was closed again, and Core restarted to load them. Before correction the
  Yellow reported 1,886 MiB total RAM, 437 MiB available, and 599 MiB of 1,024
  MiB swap in use.
- After explicit approval of the restart risk, one corrected button press was
  issued. It caused no MCP disconnect and Supervisor recorded no Core exit newer
  than the original 13:14:28 code-137 event. The press nevertheless overlapped
  the config-entry reload used to enable the button: the replacement runtime
  entities were written at 13:33:09 with a new manager reporting
  `not_prepared`, so no library result survived. This is an inconclusive attempt,
  not a pass or a native-library failure. No second press was issued. The button
  was disabled, the entry settled in `loaded`, Core remained `RUNNING`, and
  Repairs remained empty.
- After a second explicit approval, the entry was reloaded and allowed to settle
  for more than 60 seconds. The replacement entity timestamps were verified
  before exactly one press. The service completed in about 19 seconds. The
  strict helper parser accepted successful events for all five required native
  libraries and a zero-failure completion event. Entities reported runtime
  `ready`, helper `0.4.0-dev`, and native compatibility `on`; diagnostics
  reported compatibility `true` and no safe error code. Core remained
  `RUNNING`, Repairs remained empty, and Supervisor showed no exit newer than
  the original 13:14:28 failure. The runtime-probe button was disabled again.
- Disabling the config entry changed it to `not_loaded` and removed its runtime
  entity. Re-enabling restored the entry to `loaded`, cloud and credential
  booleans to `on`, and a clean `not_prepared` runtime. Configuration validation
  passed before restart. The requested restart was unusually slow; the user
  then restarted manually. Final evidence at 13:58 showed Core `RUNNING`, the
  Owlet entry `loaded`, cloud/KMS booleans `on`, runtime `not_prepared`, zero
  Repairs, no stale-runtime error, no new code-137 exit, and only Home
  Assistant's standard warning for an unverified custom integration. No direct
  process-list capture was available through MCP, so that check remains marked
  unperformed rather than inferred.

## Yellow-gate preparation — 2026-08-22

- The authenticated Home Assistant MCP connection identified the live target as
  Yellow, AArch64, Home Assistant OS 18.2, Core 2026.8.2, Python 3.14.6, and HACS
  2.0.5. Home Assistant's configuration check was valid and there were no active
  Repairs issues. This is system-health evidence, not integration-installation
  evidence.
- Authorized Firestore serial-to-KMS discovery was moved from the development
  script into `OwletCloudClient`. Sanitized tests cover one internal camera,
  direct DSN use, secret-safe credentials, and refusal to guess between multiple
  devices. The UI can retain the app-visible serial as its unique ID while the
  different internal KMS DSN remains in memory only.
- The runtime now has a supervised process-group owner, stdin-only secret input,
  bounded stdout/stderr, timeout and escalating termination, strict response
  schemas, SDK-key buffer scrubbing, safe diagnostics, and unload termination.
  Experimental runtime and frame-probe buttons are disabled by default; the
  frame button is unavailable until the runtime/library gate succeeds.
- A new clean-room build produced AArch64 `probe_libraries` SHA-256
  `b716768c79094af418d6a944e47aa65aa8bc9a2b009fdf0414718b282b8b8f6b`
  and `frame_probe` SHA-256
  `6df9db4052ccfec0debccd0e78dc4c2c8b5a7a6e7b46e7afb86360cd24b9f86b`.
  Both are PIE executables using `/runtime/bin/linker64`, depend only on Bionic
  `libc.so`/`libdl.so`, and have no writable-executable segment.
- The rebuilt no-camera helper loaded all five user-supplied libraries in the
  ARM64 emulator and returned five `ok: true` events plus a successful completion
  event. The rebuilt frame helper then received 100 real H.264 frames, 448,301
  bytes, 7 SPS, 7 PPS, 7 IDR, 1920×1080, estimated 12.5 FPS, first frame 679 ms,
  and clean shutdown.
- `scripts/build_helper_runtime.py` produced a deterministic local ARM64 archive
  SHA-256
  `4d6569dc8a4977e2522c6d80664d3cbe20a62048c3b6a650156f80eb42385033`.
  Its nine members are the two clean-room helpers, four minimal AOSP runtime
  files, two licence-notice files, and one per-file checksum manifest. The
  archive passed installation verification and scans for every configured
  secret plus common JWT, Google-key, and private-key patterns. It contains no
  Owlet application or proprietary library.
- The archive's exact Yellow launch shape was exercised in a read-only ARM64
  Linux container. An initial glibc-style `--library-path` invocation was
  correctly rejected by Bionic, so the manager was changed before deployment
  to invoke the explicit linker with a fixed, non-secret `LD_LIBRARY_PATH`.
  The corrected invocation loaded all five user libraries and returned a
  successful completion event. Camera credentials remain stdin-only.
- A temporary, unpublished Yellow deployment archive was assembled for manual
  transfer through authenticated Studio Code Server. Its SHA-256 is
  `90ee5557d8555ff51dafba077e73e7cc8b864f760abd1328faa2d9fc3c1330ed`.
  Its member list contains the integration and proprietary-free runtime only;
  the user-supplied application remains a separate ignored local file.
- Current local validation: Ruff passed, mypy passed for 35 source files, and
  `123 passed` at 86.47% branch-aware coverage. The Yellow runtime and frame
  probes remain unperformed.

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
  Full validation: Ruff passed, mypy passed for 34 source files, `92 passed` with
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
- A fresh Android 15 ARM64 Google Play emulator installed the official Dream
  3.40.0 (`64832`) package, signed into the user-confirmed EMEA account, found
  the paired camera, and displayed changing room-video pixels. Two viewport
  samples five seconds apart differed in 776,003 bytes. This is evidence only
  for official Dream playback, not for our helper.
- The current user-supplied Dream 3.40.0 ARM64 bundle had outer SHA-256
  `64cc825b54e4f59fca3f4dfe90cd01027e3b775144a769334ce1ba216ea04036`.
  Its five required libraries were byte-for-byte identical to 3.36.0 and again
  passed the extraction, architecture, symbol, and no-WX checks.
- A redacted direct-reference Firestore probe resolved the authenticated
  account document (HTTP 200), one of one service documents (HTTP 200), one of
  one device documents (HTTP 200), and one internal camera DSN. The configured
  visible identifier did not equal that internal DSN. KMS lookup using the
  internal DSN succeeded and returned only `true` presence booleans for UID,
  AuthKey, and AV password. No identifier or credential value was emitted.
- The clean-room AArch64 helper accepts SDK key, UID, AuthKey, and AV password
  in one stdin JSON object, loads user-supplied libraries in a separate process,
  and emits a fixed safe result schema. Dummy-input validation stopped at the
  SDK licence gate as expected. Real Docker/OrbStack attempts reached IOTC but
  timed out with code `-13`; no claim is made for that network environment.
- Under the Android 15 ARM64 emulator's native Bionic runtime and already-proven
  network path, three separate real probes succeeded. Probe 1: 100 frames,
  737,848 bytes, 7 SPS, 7 PPS, 7 IDR, 1920×1080, estimated 12.245 FPS, first
  frame 839 ms. Probe 2: 100 frames, 733,251 bytes, 7/7/7 SPS/PPS/IDR,
  1920×1080, estimated 12.292 FPS, first frame 967 ms. Probe 3 immediately
  followed probe 2: 100 frames, 729,888 bytes, 7/7/7 SPS/PPS/IDR, 1920×1080,
  estimated 12.790 FPS, first frame 595 ms. Every result reported clean
  shutdown, and the fixed emulator probe directory was absent afterward.
- The exact final helper source was rebuilt as AArch64 PIE with SHA-256
  `723897c1e127a361a15f1c7776ec488da1e5d514c0ff08ae924130f4c14addc7`
  and confirmed in a fourth run: 100 frames, 760,180 bytes, 7/7/7
  SPS/PPS/IDR, 1920×1080, estimated 12.278 FPS, first frame 920 ms, and clean
  shutdown. This temporary binary is not committed or distributed.
- After all helper probes had exited and the temporary emulator directory was
  confirmed absent, the user opened Dream and reported that its Android live
  video worked. This is user-observed evidence that the official app regained
  the camera session after helper teardown; it is not an official-app-open-
  during-probe concurrency test.
- FFprobe, subprocess supervision inside Home Assistant Core, Yellow lifecycle
  validation, physical outage tests, and official-app-open-during-probe behavior
  remain unperformed. The Milestone 4 Yellow acceptance gate is not passed.

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
- The user identified the hardware as probably Owlet Cam 1 and confirmed this
  is the primary account that originally paired it, not an invited caregiver
  account. A final redacted trial established an EMEA Owlet SSO session (HTTP
  200), refreshed the Firebase token, and retried KMS. KMS again returned HTTP
  403. This rules out a stale initial token or an uninitialized normal SSO
  session; no SSO or Firebase token value was printed or retained.
- A redacted device-mapping probe completed the normal EMEA Owlet SSO and Ayla
  token exchange with HTTP 200 responses. Ayla device enumeration also returned
  HTTP 200 but contained zero devices. The signed Dream APK's Retrofit
  annotations independently identified the Accounts API contract. Authenticated
  account lookup returned HTTP 200, but its response contained no DSN-named
  field; the corresponding `/devices` resource returned HTTP 404. Only status
  codes, counts, and false equality booleans were emitted. No account ID,
  device value, response body, or token was printed or retained.
- A fresh Dream Android installation exposed the missing relationship through
  authorized direct Firestore documents: Firebase UID selected the account,
  `serviceKeys` selected the service, `deviceKey` selected the device, and that
  device's internal `dsn` selected the KMS camera. Only field names, HTTP
  statuses, counts, and equality/presence booleans were emitted.
- **Local cloud/KMS core gate: passed.** Real EMEA authentication and KMS
  credential presence are proven on the ARM64 Mac. The full Milestone 1 gate is
  still unperformed because the integration has not yet run through HACS inside
  Home Assistant Core on Yellow and its required diagnostics/reauth checks have
  not been executed there.
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
