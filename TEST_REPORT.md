# Test report

Evidence is recorded conservatively. “Passed” is used only with captured test
or real-system evidence.

| Milestone | Commit | Integration version | Home Assistant version | Home Assistant OS version | Architecture | Camera model | Camera firmware | Automated tests | Yellow test | Real camera test | Result | Evidence | Unperformed tests | Known issues |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 — HACS scaffold and lifecycle | `67fae5f` | 0.1.0 | 2026.8.2 current; 2024.5.0 minimum at that milestone | HAOS 18.2 | AArch64 Home Assistant Yellow; private manual install | None | None | **Passed locally:** original 6-test lifecycle suite; later suites continue to cover lifecycle | **Partial:** manual setup, reload, unload, re-enable, restart, entity removal/restoration, and clean Owlet logs passed | Not applicable | **Lifecycle gate passed; HACS-installation gate deferred by user** | Local tests plus authenticated HA-MCP lifecycle evidence on 2026-08-22 | HACS custom-repository acceptance, HACS Action and Hassfest in GitHub context | Public repository intentionally deferred until core functionality works |
| 1 — Cloud authentication and KMS | `165093f` | 0.2.0 | 2026.8.2 current; 2024.11.0 minimum | HAOS 18.2 | AArch64 Yellow | Owlet Cam 1, user-reported; not hardware-verified | Not established | **Passed locally:** Milestone 1-era full suite 125 tests at 86.49% branch-aware coverage; Ruff and mypy passed | **Partial:** manual install, setup, reload, entities, cloud/KMS, and redacted diagnostics passed | **Passed on Yellow:** EMEA authentication, authorized camera discovery, and KMS credential-presence validation | **Cloud/KMS Yellow core path passed; full Milestone 1 gate incomplete** | Loaded config entry; cloud and credential booleans on; diagnostics redacted email, password and camera identifier | HACS installation and wrong-password reauthentication correction | The app-visible serial differs from the internal KMS DSN; the production client resolves this relationship while keeping the internal value in memory only |
| 2 — External bridge | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All | Blocked by Milestone 0 gate |
| 3 — Embedded ARM64 runtime probe | `165093f`, revalidated with `11ba0f7` | 0.2.0 base; helper 0.4.0-dev; no embedded release | Core 2026.8.2 | HAOS 18.2 | Yellow AArch64; ARM64 macOS/Docker/emulator local targets | Owlet Cam 1, user-reported | Not established | **Passed locally:** Milestone 3-era full suite 126 passed at 86.60% coverage; Ruff and mypy passed | **Passed native capability gate after correction:** runtime `ready`, all five required libraries loaded, unload/re-enable and restart recovered cleanly | No-camera library probe passed on Yellow; no camera connection attempted | **Yellow native runtime gate passed; release-distribution checks remain** | Helper 0.4.0-dev, compatibility `true`, no safe error, Core remained loaded, zero Repairs, and direct `ps` checks found no probe helper after the revalidation | HACS release asset download, separate `probe_runtime` command, detected APK version reporting, GitHub release build | Initial in-memory extraction caused code 137; disk-spooling correction passed. Restart was unusually slow and the user performed an additional manual restart; final setup was clean |
| 4 — Embedded connection and frame probe | `11ba0f7` plus 2026-08-22 live evidence | Development-only; no embedded release | Core 2026.8.2 | HAOS 18.2 | Yellow AArch64; Android 15 ARM64 emulator on ARM64 macOS | Owlet Cam 1, user-reported | Not established | **Passed:** 126 tests at 86.60% coverage; Ruff and mypy passed; session-mode helper passed compile, ELF, safe-error, checksum and atomic-install validation | **Passed:** repeated 100-frame probes, rapid reacquisition, Dream-open behavior, post-Dream reacquisition, live `lan` mode, clean shutdown, and three empty direct orphan-process captures | **Passed on Yellow:** real H.264 with SPS/PPS/IDR; helper connected while Dream was actively showing video and reacquired 1080p after Dream closed; earlier Dream post-probe recovery was user-confirmed | **Complete Milestone 4 Yellow gate passed** | Initial three probes: 1920×1080, 13.599–14.341 FPS, 71–262 ms. Dream-open probe: 228,479 bytes, 640×360, 13.7 FPS, 232 ms, `lan`. Dream-closed probe: 530,039 bytes, 1920×1080, 13.814 FPS, 343 ms, `lan`. Every probe had 100 frames, 7/7/7 SPS/PPS/IDR and clean shutdown; entry loaded, zero Repairs, no Owlet error, no orphan helper | Snapshot/camera entity, continuous streaming, physical outage/power-cycle tests | Docker/OrbStack IOTC timed out with `-13`; Dream-open session selected 640×360 while the Dream-closed session returned to 1080p; no claim is made that Dream itself remained uninterrupted during the helper probe |
| 5 — Snapshot-only embedded camera | `3f2a73a` | 0.2.0 integration base; helper 0.5.0-dev; no embedded release | Core 2026.8.2 | HAOS 18.2 | Yellow AArch64; local macOS ARM64 plus reproducible AArch64 Linux build | Owlet Cam 1, user-reported | Not established | **Passed locally:** 149 tests at 86.97% coverage; Ruff, mypy, secret/release checks; both helper modes pass freestanding compilation; runtime archive reproducible and atomically installable | **Passed:** clean setup/restarts, runtime gate, native camera entity, real JPEGs, ten sequential calls, simultaneous API callers, two independent dashboard clients, standard `camera.snapshot`, periodic dashboard soak, stable memory, zero active Repairs and no new Owlet traceback | **Passed snapshot path:** real 1920×1080 and 864×480 source captures decoded to JPEG; standard snapshot service produced a valid baseline 864×480 JPEG; user confirmed Dream live video recovered after the final run | **Complete Milestone 5 Yellow gate passed** | Initial visible 1920×1080 JPEG; nine additional cache-expired fresh captures succeeded before Owlet rate-limited the tenth KMS lookup. The resulting stuck-state bug was corrected and covered by regression tests. Post-fix: fresh capture succeeded; ten rapid sequential calls returned valid JPEGs (first 2265 ms; cached calls 37–79 ms); two simultaneous API callers received one identical JPEG in 1873 ms; simultaneous in-app-browser and Chrome reloads both showed the camera, runtime `ready`, and no lost connection. During a 30-minute two-dashboard periodic-snapshot soak, Core memory decreased from 815,271,936 bytes (41.22%) to 801,710,080 bytes (40.54%); CPU samples were 5.41% then 1.74%. `camera.snapshot` hash `25d7a7a1…06d8` was independently verified before both remote and local test copies were deleted | Physical camera/Wi-Fi outages; entry unload during a real snapshot; direct process enumeration inside the Core PID namespace | Owlet rate-limits repeated fresh KMS lookups; the five-second cache prevents ordinary rapid calls from amplifying KMS/session use. The pre-fix rate-limit traceback remains in historical logs, but no new traceback appeared after the corrected restart. The supported SSH add-on lacks Core/host PID visibility; no host PID, Docker or privileged workaround was enabled, so direct Core-namespace orphan enumeration remains unperformed |
| 6 — Embedded live H.264 stream | `7b25b21`, `e6b79ea`, `c6bb2b3` plus this 2026-08-23 gate commit | 0.2.0 integration base; helper 0.6.0-dev; no embedded release | Core 2026.8.2 | HAOS 18.2 | Yellow AArch64; reproducible AArch64 Linux build | Owlet Cam 1, user-reported | Not established | **Passed locally:** 189 tests at 85.86% branch-aware coverage; Ruff, mypy, secret scan and release validation passed; two independent helper builds were byte-identical | **Partial:** Core-local FFprobe, real changing live video, two simultaneous viewers, idle/reopen, `camera.snapshot`, `camera.record`, automatic settled-reload, active-viewer reload, cold-restart readiness and a shortened continuous-view test passed; final run had zero Repairs and zero matching system-log entries | **Passed bounded media path:** Home Assistant rendered real room frames; Core-local FFprobe verified H.264 Baseline level 4.0 at 1920×1080, 15 FPS and 708.3 kbit/s; snapshot and recording services produced real media | **Bounded media path and automatic runtime recovery passed; full Milestone 6 gate incomplete** | FFprobe counted 124 MPEG-TS frames; producer observed 127 frames/892,524 bytes and zero reconnects. Two dialogs showed real video. Active-viewer reload recovered automatically. After the timestamp-reset correction, restart plus live → idle → live ended idle at 4,201 aggregate frames. A later continuous session ran 7m44.65s and advanced aggregate counters from 6,039 to 12,917 frames and 40,200,193 to 79,551,199 bytes; it then reached idle with zero consumers/reconnects, zero matching system-log entries and zero Repairs | Formal two-hour and overnight soaks; companion app inside/outside LAN; Dream-open continuous-stream coexistence; physical outage/power-cycle/Yellow reboot; direct Core PID orphan enumeration | Initial raw H.264 lacked DTS and was replaced by timestamped MPEG-TS. A later idle-to-new-session timestamp discontinuity was caught by the clean-log gate, fixed by resetting cached media/timestamps for each new producer, and absent after restart and repetition |
| 7–8 — Upload UI through stable release | — | — | — | — | — | — | — | Unperformed | Unperformed | Unperformed | Not started | — | All upload, hardening and release gates | External bridge and HACS-publication work remain separately deferred by user |

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

No HACS acceptance, physical outage, RTSP, extended-soak or stable-release claim
is made by this report. The live-dashboard claim is limited to the bounded real
Milestone 6 evidence below; automatic runtime recovery passed, while the full
continuous-stream acceptance gate remains incomplete.

## Milestone 6 bounded live-stream validation — 2026-08-22 through 2026-08-23

- Two independent clean-room ARM64 helper builds produced the same
  proprietary-free archive, SHA-256
  `c754bd80cb0c321ffaa26c2db8c7905380e2400005bd622095ec004cf3b7cf68`.
  The private integration/runtime deployment archive had SHA-256
  `bfc718da2ba1d2f4f740b4d3c9820c8592dfe7dea94b99a544fd29e6fb4827f4`;
  Yellow independently computed the same value before installation. Neither
  archive contains the user's application, proprietary library, SDK key or
  camera credential.
- Home Assistant initially failed to import the deployed integration because
  rollback copies containing manifests had been left under
  `custom_components`. They were moved to `/config`, outside integration
  discovery, and the rollback-aware deploy script was corrected before further
  testing. Core then started with valid configuration, no Owlet import error and
  no active Repair.
- The first media transport exposed raw Annex-B H.264 over loopback HTTP. It
  displayed video, but Home Assistant's stream worker reported seven consecutive
  packets without DTS. That attempt failed acceptance. The source was replaced
  with independently implemented MPEG-TS tables, PES timestamps and PCR while
  preserving copy-only H.264. The corrected source file's deployed SHA-256 was
  `5ec9ee2152633a2a6f0b51aa90f205a65f7ddfc653fd33d6f43926f77a71bb65`.
- The corrected source is bound to `127.0.0.1` on an ephemeral port with an
  unguessable path. It waits for SPS/PPS/IDR before reporting healthy, starts one
  TUTK producer for the first consumer, fans out to multiple consumers, and
  supports bounded reconnect and idle teardown. No second go2rtc process,
  global go2rtc configuration, LAN listener or video transcode is used.
- Home Assistant's native camera dialog displayed real changing infrared room
  frames. Two samples 3.5 seconds apart were about 49 kB each and differed in
  47,896 encoded bytes, establishing that the result was not one cached still.
  Two simultaneous authenticated Home Assistant viewers displayed real frames.
  Reopening after idle also displayed real frames.
- Live redacted diagnostics reported `streaming`, active and healthy, 389
  frames, two consumers, zero reconnects and loopback binding. After both
  viewers and Home Assistant's managed stream consumers closed, the final state
  reported `idle`, inactive, 1,838 frames, zero consumers and zero reconnects.
  There were no active Repairs or current Owlet system-log entries.
- Standard `camera.snapshot` wrote a valid real-room JPEG. Standard
  `camera.record` wrote a playable five-second real-room MP4. Both temporary
  validation files were deleted from Yellow after verification; they are not
  recoverable there but can be reproduced by calling the services again.
- The first reload was requested while two WebRTC viewers were active. The entry
  remained in `unload_in_progress` until both viewers closed, then reached
  `loaded`; at that point an explicit runtime probe was still required. The
  recovery correction now stores only an exact mode-0600 marker recording prior
  explicit validation and reruns archive, checksum, ELF and isolated `dlopen`
  gates on every restore. It does not persist or trust native capability data.
- On 2026-08-23 a cold Core restart loaded the entry, waited until Home
  Assistant emitted its public startup-complete event, moved through
  `preparing`, and automatically reached `ready` with helper `0.6.0-dev`,
  compatibility true and no safe error. The final startup listener used Home
  Assistant's callback marker so the event-loop signal was not dispatched to a
  worker thread. A no-viewer config-entry reload returned in 3.657 seconds,
  immediately showed `preparing`, and automatically returned
  to `ready` within the next 30-second observation interval. No probe button was
  pressed in either recovery sequence.
- The first callback-marked Yellow restart exposed one standard-system-log error
  when the `finally` path attempted to remove an already-consumed one-shot
  listener. That intermediate result failed the clean-log gate. Commit
  `c6bb2b3` skips manual removal after the event fires and adds a log regression
  assertion. The final cold restart again reached `ready` automatically; the
  subsequent system-log search returned zero Owlet entries, Repairs remained
  empty, and configuration remained valid.
- A repeated active-viewer reload began after diagnostics showed real media:
  `streaming`, healthy, 1,147 frames, two consumers and zero reconnects. The
  native producer stopped and its loopback binding closed, but the entry stayed
  `unload_in_progress` while one Home Assistant-managed consumer remained. Once
  the camera dialog closed, reload completed in the background, revalidation
  moved through `preparing`, and automatically returned to `ready`, idle, zero
  consumers and loopback-only binding. No undocumented go2rtc interface was
  used to force-close the provider session.
- The retained-consumer hang was reproduced under Python 3.14: awaiting the
  closed `asyncio.Server` also waited for accepted connections while Home
  Assistant retained the loopback source. The correction first stops accepting
  connections, disconnects and bounds tracked client handlers, aborts a writer
  that does not close within the deadline, and only then awaits the server.
  Entity removal also stops Home Assistant's public camera stream worker while
  the integration-owned source is still available, preventing that worker from
  retrying a stale per-entry URL after reload.
- After the exact corrected `stream.py` and `camera.py` files were
  checksum-verified on Yellow, Core was restarted once to import them. The
  runtime automatically reached `ready`; the native camera dialog displayed a
  real infrared frame; and active-viewer reload returned successfully in 4.318
  seconds. The entry was already `loaded` at the first follow-up check 1.2
  seconds later. The dialog remained present through reload. After automatic
  native revalidation, closing and reopening that retained dialog displayed a
  fresh real frame from the replacement entity. With all camera surfaces
  closed, the configured idle timeout returned the entity to `idle` while the
  runtime remained `ready`. System-log searches found zero Owlet, demuxing or
  connection-refused entries and Repairs remained empty.
- Local validation after the unload correction: `163 passed`, 86.53%
  branch-aware coverage, Ruff format/check and mypy passed. Focused transport
  tests validate PAT/PMT CRCs and PIDs, PES timestamping, 188-byte packetization,
  private-path rejection, multi-consumer fan-out and bounded shutdown with a
  retained consumer. Entity tests verify Home Assistant's stream worker is
  stopped during removal. Recovery tests require an exact private consent
  marker, defer cold-start work until Core is running, and schedule one restore
  per setup/reload. Secret scan, release validation and `git diff --check` also
  passed.
- On 2026-08-23 a disabled-by-default Core-local probe used Home Assistant's
  configured FFprobe sibling against the loopback source. It counted 124 H.264
  Baseline level-4.0 frames at 1920×1080 and 15 FPS in MPEG-TS. The producer
  observed 127 frames and 892,524 bytes during the bounded interval, yielding
  708.3 kbit/s, with zero reconnects. No raw FFprobe output, source URL or
  secret was retained.
- Two standard Home Assistant camera dialogs then displayed the real room while
  diagnostics advanced from 1,274 to 1,320 frames in three seconds and later
  reached 1,840, with two loopback consumers and zero reconnects. A config-entry
  reload while viewing returned the entry to `loaded`, automatically restored
  native readiness, and the retained camera surface resumed real video. The
  producer later stopped at idle with zero consumers. Standard
  `camera.snapshot` produced a verified 864×480 JPEG; a bounded ten-second
  `camera.record` request produced an MP4 that Chrome opened and rendered with
  a real frame. The temporary media files were then deleted from Yellow and are
  not recoverable there.
- The first clean-log review found one timestamp-discontinuity entry when a new
  producer reused an old cached GOP and wall-clock timestamp origin after an
  idle interval. That attempt failed the log gate. The listener now discards
  cached media and resets MPEG-TS timestamps before each new native producer.
  The checksum-verified correction was deployed with a rollback archive and
  Core restarted. Two real live sessions separated by a complete idle stop then
  displayed correctly. The final state was idle/inactive at 4,201 aggregate
  frames, zero consumers and zero reconnects; structured system-log search
  returned zero matching entries and Repairs returned zero.
- A shortened practical viewing test ran continuously from
  10:58:35.882841 to 11:06:20.532237 Europe/Stockholm on 2026-08-23
  (7 minutes 44.65 seconds). The camera dialog displayed a real room frame and
  live diagnostics were healthy with one consumer and zero reconnects. Across
  the test window, aggregate counters advanced from 6,039 to 12,917 frames and
  from 40,200,193 to 79,551,199 bytes. Home Assistant recorded a normal
  `streaming` to `idle` transition; final diagnostics were idle/inactive with
  zero consumers and zero reconnects. Structured Owlet system-log search and
  active Repairs both returned zero. This passes the shortened practical test,
  not the formal two-hour soak.
- Formal two-hour viewing, overnight idle/reconnect, companion-app access,
  Dream-open continuous-stream coexistence, physical camera/Wi-Fi/internet
  interruptions, Yellow reboot, and direct Core-namespace orphan-process
  enumeration were not performed. The bounded media path passes; the complete
  Milestone 6 gate does not.

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
- After a fresh reload-settled library probe, exactly three bounded real-camera
  frame probes ran on Yellow. Probe 1 received 100 frames and 450,104 bytes,
  with 7 SPS, 7 PPS, 7 IDR, 1920×1080, estimated 14.196 FPS, 81 ms to first
  frame, and clean shutdown. Probe 2 received 100 frames and 450,118 bytes,
  with 7/7/7 SPS/PPS/IDR, 1920×1080, 14.341 FPS, 71 ms to first frame, and
  clean shutdown. Probe 3 immediately followed probe 2 and received 100 frames
  and 451,325 bytes, with 7/7/7 SPS/PPS/IDR, 1920×1080, 13.599 FPS, 262 ms to
  first frame, and clean shutdown. The rapid second and third sessions did not
  collide. Home Assistant remained `RUNNING`, Repairs stayed empty, Supervisor
  showed no exit newer than the original extraction failure, and Owlet emitted
  no integration error. Both probe buttons were disabled afterward without
  discarding the cached final result.
- After the probes exited, the user opened Dream and confirmed that its live
  camera feed worked. This is user-observed evidence that Dream reclaimed the
  camera after the Yellow helper disconnected; it is not evidence for Dream
  already being open during a helper probe.
- A follow-up clean-room change adds only the bounded session-mode enum (`p2p`,
  `relay`, or `lan`) using the SDK's session-check call; UID, address, port and
  NAT details are scrubbed and never emitted. The Python boundary rejects any
  other value. The rebuilt AArch64 helper passed its 64-byte ABI layout guard,
  freestanding compile, ELF checks, network-disabled safe-error execution, and
  atomic runtime-archive installation. Its local archive SHA-256 is
  `147e84b2a35e077718f86607b01dbe57165823a4c2683a2c6548e9f2d6fcf098`.
  It was then deployed to Yellow with all three transferred-file hashes verified
  before atomic replacement; the previous runtime and Python modules were kept
  as explicit rollback copies.
- After a Core restart and more than 60 seconds of reload settling, one approved
  runtime re-probe returned `ready`, helper `0.4.0-dev`, compatibility `true`,
  and no safe error. A direct process-list check found no surviving
  `probe_libraries` or `frame_probe` process.
- The user opened Dream, confirmed moving live video, and kept it open while the
  first bounded helper probe ran. The helper received 100 frames and 228,479
  bytes, with 7 SPS, 7 PPS, 7 IDR, 640×360, 13.7 FPS, 232 ms to first frame,
  observed `lan` mode, and clean shutdown. This records successful helper
  behavior while Dream was active; it does not claim Dream was uninterrupted.
- After the user closed Dream, the second and final approved probe immediately
  reacquired the camera and received 100 frames and 530,039 bytes, with 7/7/7
  SPS/PPS/IDR, 1920×1080, 13.814 FPS, 343 ms to first frame, `lan`, and clean
  shutdown. The lower coexistence resolution and return to 1080p after Dream
  closed are recorded observations, not an inferred camera policy.
- Direct process-list checks after the runtime probe and after each frame probe
  returned no helper process. The config entry stayed `loaded`, Repairs stayed
  empty, and the only Owlet-matching log issue was Home Assistant's standard
  unverified-custom-integration warning. Temporary SSH was then closed: zero
  keys, empty password, forwarding disabled, null port mapping, and a direct
  port-22222 attempt was refused. These results complete the Milestone 4 Yellow
  acceptance gate. No snapshot, camera entity, continuous stream, or physical
  outage claim is made.

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
  `125 passed` at 86.49% branch-aware coverage. The Yellow library gate and
  three bounded Yellow frame probes passed; continuous streaming remains
  unperformed.

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
- FFprobe, physical outage tests, direct/relay observation, direct process-list
  inspection, and official-app-open-during-probe behavior remain unperformed.
  The Milestone 4 Yellow H.264 receipt sub-gate passed, but the complete
  coexistence gate is not yet passed.

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
