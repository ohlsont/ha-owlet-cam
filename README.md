# Owlet Cam for Home Assistant

Owlet Cam is a clean-room Home Assistant custom integration intended to expose
Owlet cameras as native camera and room-sensor entities. It is not affiliated
with, endorsed by, or supported by Owlet or ThroughTek.

## Current status: Milestone 7 accepted on Yellow

Version `0.7.0` implements clean-room, asynchronous Owlet cloud authentication
and camera KMS validation. Embedded Experimental setup can validate a European
or World/US account. The production cloud client follows authorized Firestore
account → service → device references when a Cam 1's app-visible serial differs
from its internal KMS DSN; that internal value is kept in memory only.

The integration creates cloud diagnostics plus cached experimental runtime
diagnostics. The first native validation starts only after the
disabled-by-default **Run runtime probe** button is explicitly enabled and
pressed. A successful explicit probe writes a private, non-secret consent
marker; later reloads and restarts repeat every archive, checksum, ELF and
isolated-library gate automatically. Cold-start revalidation waits for Home
Assistant's public startup-complete event so it does not compete with Core on a
memory-constrained Yellow. A separately supervised child process receives
secrets through stdin only; config-entry unload terminates its process group and
scrubs the cached SDK key.

Core cloud entities include:

- `binary_sensor.<camera>_cloud_reachable`
- `binary_sensor.<camera>_camera_credentials_available`
- `sensor.<camera>_authentication_expiry`

The credential-availability entity is boolean only. Firebase tokens, camera UID,
AuthKey, AV password, and account identifiers are not exposed in entity state,
attributes, diagnostics, logs, or frontend errors.

External bridge mode now connects to the current `btoth525/Owlet-To-Rtsp` HTTP
API, discovers one or several cameras, and creates a native Home Assistant
camera plus metric temperature, humidity, sound, illuminance, Wi-Fi and health
entities. Snapshot and room-sensor endpoints are optional; their absence does
not break RTSP video. This path has comprehensive fake-bridge coverage but has
not yet been exercised against a real external bridge.

A redacted real-account probe has authenticated successfully against the
user-confirmed EMEA project. Direct
authorized Firestore account → service → device references resolved one
internal camera DSN; that value differs from the identifier Dream displays to
the user. Regional KMS validation using the internal DSN succeeded and emitted
only credential-presence booleans. No account, device, token, DSN, UID, AuthKey,
AV password, or SDK key value was retained or displayed. This discovery path is
now used by the Home Assistant client and config flow.
The source is held in a private GitHub repository while release hardening is in
progress. A private manual Yellow installation now proves
that the entry loads, EMEA cloud/KMS validation succeeds, entities appear, and
diagnostics redact configured secrets. This is not HACS-installation evidence.

The first Yellow runtime probe encountered system memory pressure: Supervisor
recorded Core and Matter processes exiting with code 137 while the original
extractor held a nested APK in memory. Core recovered automatically. Nested APKs
are now streamed to private disk files and stale extraction directories are
process-session scoped.
One corrected press caused no new Core exit, but it overlapped the asynchronous
config-entry reload and its runtime manager was replaced before a result could
be retained. A subsequent reload-settled probe completed in about 19 seconds on
the Yellow: the isolated helper loaded all five required user-supplied ARM64
libraries, reported zero failures, and left Core running with no Repairs or new
process exit. Entry unload/re-enable and restart also recovered cleanly. A later
revalidation with direct process-list access again passed and left no helper
process. The native capability gate is passed; HACS release-asset distribution
remains unperformed.

On the separate local feasibility branch, validly signed Owlet 3.36.0 and
3.40.0 ARM64 bundles have passed safe extraction, ELF, required-symbol, and
isolated Bionic `dlopen` checks. The application and extracted proprietary files
remain ignored under `userfiles/` and are not part of the repository. A
clean-room isolated helper completed repeated 100-frame probes on an Android 15
ARM64 emulator: each contained real H.264 SPS/PPS/IDR NAL units,
parsed as 1920×1080, and shut down cleanly. This is strong local feasibility
evidence. The same clean-room helper has now completed three bounded 100-frame
probes inside Home Assistant Core on Yellow. Every Yellow probe contained real
H.264 SPS/PPS/IDR units, parsed as 1920×1080, and reported clean shutdown. This
is not snapshot, RTSP, camera-entity, or dashboard-stream evidence. The
session-mode build was subsequently deployed and connected in `lan` mode while
Dream was actively displaying live video. That coexistence probe received 100
valid frames at 640×360; after Dream closed, a second probe immediately
reacquired 100 valid frames at 1920×1080. Both shut down cleanly, and direct
process-list checks found no orphan helper.

Milestone 5's snapshot-only gate now passes on Yellow. A separate snapshot
helper waits for one Annex-B access unit
containing SPS, PPS and IDR, writes it only to a private inherited file
descriptor, and exits after clean session teardown. Home Assistant decodes the
private mode-0600 temporary H.264 file with its pinned FFmpeg component,
validates JPEG framing, caches the result for five seconds, and serializes
concurrent requests. Yellow produced visible 1920×1080 and 864×480 JPEGs; ten
sequential calls, two simultaneous API callers, two independent dashboard
clients and `camera.snapshot` passed. During a 30-minute periodic dashboard
snapshot soak, Core memory decreased by 1.66%, and the user confirmed Dream
reclaimed live video afterward. At that milestone the camera entity claimed no
stream feature; the separately gated Milestone 6 path described below now does.
Direct process enumeration inside the Core PID namespace remains unperformed:
the supported SSH add-on cannot see that namespace, and no host-PID, Docker or
privileged workaround was enabled.

A deterministic release workflow now creates a checksum-manifested ARM64 runtime
containing only four clean-room helpers, a minimal pinned AOSP Bionic runtime,
and licence notices. Release assets are inspected against configured secrets,
common token patterns and proprietary filenames; no user application or
proprietary library may be included. The integration can download only the
exact helper version matching its own release and verifies the published
SHA-256 before atomic installation. Release hosting remains unperformed.

Milestone 6 now has a bounded real-media result on Yellow. One isolated helper
owns the TUTK session and emits length-framed Annex-B H.264. The integration
adds timestamps and packages the access units into a single-program MPEG-TS
source bound to `127.0.0.1`; Home Assistant's supported stream stack consumes
that source. No video transcoding occurs and no second go2rtc process or global
configuration is used. A raw-H.264 first attempt was rejected after Home
Assistant reported missing DTS; it was replaced before acceptance testing.

The corrected source displayed changing real infrared room frames in Home
Assistant for two simultaneous authenticated viewers. Reopening after idle
worked, standard `camera.snapshot` produced a valid JPEG, and
`camera.record` produced playable bounded MP4 files. Live diagnostics observed
one producer, two consumers, healthy media and zero reconnects; after the
viewers closed, diagnostics reached idle with zero consumers. Automatic runtime
revalidation now restores `ready` after a settled config-entry reload and after
a cold Core restart without another button press. Active-viewer reload is now
bounded: entity removal stops Home Assistant's public camera-stream worker
before the integration tears down its loopback source, and loopback shutdown
does not wait indefinitely for a retained consumer connection. On Yellow a
reload with the live camera dialog open returned in 4.318 seconds, the entry was
already `loaded` at the first follow-up check, and no Owlet, demuxing or
connection-refused system-log entry appeared.

A later Core-local FFprobe gate inspected the real loopback source from inside
Home Assistant: H.264 Baseline level 4.0, 1920×1080, 15 FPS, 708.3 kbit/s and
124 counted frames in MPEG-TS. The same active-viewer reload then recovered the
already-open Home Assistant camera surface automatically. A clean-log follow-up
found and corrected one idle-to-new-session timestamp discontinuity by clearing
the old GOP and timestamp origin before a new native producer. After a Core
restart, two separate real live sessions with a complete idle disconnect between
them reached 4,201 aggregate frames, zero reconnects, zero consumers at final
idle, zero Owlet/stream system-log entries and zero Repairs. A later shortened
continuous-view test ran for 7 minutes 44.65 seconds, advanced the aggregate
counter by 6,878 frames, and returned normally to idle with zero consumers,
zero reconnects, no matching Owlet system-log entry and no active Repair. This
is practical bounded evidence, not a two-hour soak. On 2026-08-23 the user
explicitly waived the formal two-hour/overnight, Companion-app, Dream
coexistence, physical-outage and additional Yellow-reboot checks. Milestone 6
is accepted under that revised validation scope; those checks remain listed as
unperformed and are not implied to have passed.

Milestone 7 adds an administrator-only **Owlet Cam Runtime** sidebar panel. It
streams APK/APKM/XAPK/ZIP uploads directly to a generated mode-0600 file under
`userfiles/uploads`, shows upload progress, exposes only redacted runtime facts,
and provides bounded authentication, runtime, frame, stream-health and restart
controls. The default behavior deletes the uploaded archive after successful
extraction; a grouped embedded option can retain it. The extracted ARM64
libraries and SDK key remain private so automatic post-restart validation can
continue without asking for the archive again. A confirmation-gated action
deletes all uploaded applications, extracted proprietary libraries and stored
SDK material while retaining the verified open-source helper runtime.

Actionable Home Assistant Repairs now track missing/incomplete applications,
wrong architecture, missing libraries or SDK key, unsafe storage, checksum and
runtime incompatibility, reauthentication, obsolete helpers, and repeated
stream recovery failure. Resolved conditions remove their issue automatically.
The panel and its bounded runtime, frame, and stream-health actions are now
deployed and exercised on Yellow. Redacted diagnostics reported a real
100-frame 1920×1080 probe and a Core-local H.264 Baseline stream probe while
all helper children were reaped. A config-entry reload then exposed a fast-exit
stdin race in no-input helpers; the regression fix is installed on Yellow and
covered locally. After a post-fix Core restart, automatic validation returned
to `ready` with all five libraries compatible, no safe error, one helper
started/reaped, zero forced kills, zero active Repairs, and no current Owlet
system-log entries. The final real panel cycle then deleted every proprietary
file, raised the expected missing-application Repair, accepted a 154,946,466-byte
user-selected XAPK, cleared the Repair, deleted the uploaded archive after
extraction, and restored `ready` with all five libraries compatible. Milestone 7
is accepted on Yellow.

## Runtime modes

- **External bridge** connects to an independently running, compatible
  `btoth525/Owlet-To-Rtsp` bridge and exposes its RTSP camera and room sensors
  without MQTT or a separately configured Generic Camera entity.
- **Embedded experimental** uses a separately supervised native helper. It
  will never load proprietary native libraries into Home Assistant's Python
  process. Users prepare a compact personal runtime package from their own
  installed Owlet application outside Home Assistant.

External mode will remain available as a fallback after embedded mode exists.

## Supported installations

The minimum Home Assistant version is `2024.11.0`. Typed
`ConfigEntry.runtime_data` and reconfigure flows existed earlier, but 2024.11 is
the first release containing every reauth/reconfigure helper used by this
implementation, including `_get_reauth_entry`, `_get_reconfigure_entry`, and
the unique-ID mismatch guard.

The primary target is Home Assistant Yellow running Home Assistant OS on
AArch64. Cloud/KMS, the corrected native runtime gate, repeated H.264 frame
receipt, Dream-open helper behavior, session-mode reporting, and orphan-process
checks have passed on that target. HACS installation remains unperformed.

## Install as a HACS custom repository

1. After this repository is public and has a release, in HACS open the custom
   repositories dialog. HACS cannot install this intentionally private
   development repository.
2. Add `https://github.com/ohlsont/ha-owlet-cam` with category **Integration**.
3. Download **Owlet Cam** and restart Home Assistant.
4. Add **Owlet Cam** from Settings → Devices & services. Choose **External
   bridge** and enter its HTTP(S) control-panel URL, or choose **Embedded
   experimental** and enter the Owlet account, region, camera serial, and camera
   name. The serial shown in Dream is accepted even when Owlet uses a different
   internal KMS identifier.

The temporary Milestone 0 lifecycle mode remains hidden from ordinary setup and
is available only when Core starts with `OWLET_CAM_DEV_MODE=1`.

## Prepare the embedded runtime package

The recommended embedded input is a `.owletcam` file created on a desktop. It
contains only the five required ARM64 libraries, the user-owned SDK licence key,
and integrity metadata. It contains no Android code/resources, Owlet account
credentials, camera credentials or tokens. The resulting file is private
proprietary material: do not publish or share it.

With Dream already installed on one authorized Android device or Play-enabled
Android Studio emulator, download the checksum-listed `owlet-cam-prepare.pyz`
asset from the matching integration release and run:

```bash
python3 owlet-cam-prepare.pyz adb owlet.owletcam
```

When multiple devices are connected, pass `--serial DEVICE`. The tool supports
both the current Dream package (`com.owletcare.sleep`, default) and the legacy
Owlet Care package (`--package com.owletcare.owletcare`). It uses `adb shell pm
path` and `adb pull`; it does not read application data or Owlet credentials.

Advanced users may instead use apkeep's Google Play backend. Configure apkeep
itself in a private mode-0600 INI file, then pass only that file's path:

```bash
chmod 600 /path/to/apkeep.ini
python3 owlet-cam-prepare.pyz apkeep owlet.owletcam \
  --config /path/to/apkeep.ini
```

The Google email/token never appears in the preparer's command arguments or
output. apkeep warns that Google may terminate accounts for Terms-of-Service
violations; this is therefore an optional expert workflow, not the default.
Downloading through apkeep's third-party APKPure backend is not supported.

An existing APK/APKM/XAPK can also be minimized without downloading anything:

```bash
python3 owlet-cam-prepare.pyz archive dream.xapk owlet.owletcam
```

Upload `owlet.owletcam` in the administrator-only **Owlet Cam Runtime** panel.
The integration independently verifies the fixed package schema, hashes, SDK
key shape, AArch64 ELF structure and required symbols, then deletes the upload
by default. Direct full-application upload remains a development fallback.

## Configuration and screenshots

Configuration, reauthentication, reconfiguration, and grouped general,
external and embedded options are implemented in the UI. Defaults favor
stability and coexistence:
keep-warm, audio, direct-P2P preference, and experimental local sensors are all
off. Retaining the uploaded runtime package is also off by default. Administrators
manage user-supplied runtime files and native probes from the **Owlet Cam
Runtime** sidebar panel. Real Yellow UI video was visually verified, but no
screenshot containing the user's room is committed to this repository.

## Privacy and security

Account email and password live in Home Assistant config-entry data. Short-lived
Firebase and KMS camera credentials are kept only in memory. User-supplied
libraries and the extracted SDK key are private mode-0500/mode-0600 files under
`custom_components/owlet_cam/userfiles/`, which HACS preserves but Git and
release checks exclude. The authenticated panel can delete all proprietary
material. See [SECURITY.md](SECURITY.md).

## Known limitations

- External bridge mode is implemented and covered with hand-authored responses
  matching commit `132620a85ff422b451e52fdbf2076abb3975e9ec`, but its real
  bridge/video gate is unperformed. The inspected bridge has no versioned API
  field and exposes sensitive camera fields in `/api/cameras`; this integration
  deliberately ignores those fields and parses only safe status metadata.
- The embedded camera's snapshot path and bounded continuous Home Assistant
  stream path have displayed real media on Yellow. The loopback source is
  timestamped MPEG-TS carrying copied H.264, not RTSP. Milestone 6 is accepted
  under a user-approved reduced validation scope; formal two-hour/overnight,
  Companion-app, Dream-coexistence and physical-outage checks were waived and
  remain unperformed. Active-viewer reload, settled reload and Core-restart
  recovery are automatic after the first explicit native validation.
- Cloud/KMS behavior has comprehensive sanitized fixture coverage and succeeded
  inside Home Assistant Core on Yellow. Wrong-password reauthentication and the
  complete Milestone 1 acceptance sequence remain unperformed.
- Manual Yellow installation is proven; HACS installation and helper release
  download are not. The initial
  native probe hit code-137 memory pressure. A corrected press caused no new
  exit but was invalidated by a still-completing config-entry reload. A later
  reload-settled probe passed all five library loads on Yellow.
- The native libraries require Bionic and cannot be loaded by glibc. The local
  minimal Bionic probe, Yellow library probe, Yellow frame probe, and Android
  emulator frame probe passed. Docker/OrbStack IOTC timed
  out, so that network environment is not claimed as compatible.
- Five Yellow probes each received 100 real H.264 frames with SPS/PPS/IDR and
  clean shutdown. Three initial probes were 1920×1080 at 13.599–14.341 FPS. A
  later Dream-open coexistence probe reported `lan`, 640×360 and 13.7 FPS; after
  Dream closed, the helper immediately reacquired `lan`, 1920×1080 and 13.814
  FPS. Direct checks found no orphan helper. This passes the bounded frame-probe
  gate but is not snapshot or continuous-stream evidence, and it does not claim
  Dream itself remained uninterrupted during the helper probe.
- The bounded Milestone 6 run showed changing real frames in two Home Assistant
  clients, valid service snapshots, playable service recordings, one producer
  with two consumers, zero reconnects, and later idle states with zero
  consumers. Core-local FFprobe recorded H.264 Baseline level 4.0, 1920×1080,
  15 FPS, 708.3 kbit/s and MPEG-TS. Automatic post-restart, settled-reload and
  active-viewer reload recovery passed on Yellow. A timestamp discontinuity
  found during idle-to-new-session testing was corrected; the repeated
  restart, live, idle and live sequence ended with zero matching system-log
  entries and zero Repairs.
- Stream diagnostics retain redacted session, stop, reconnect, last-frame,
  interruption and recovery timestamps/codes. Unexpected interruptions emit a
  fixed safe-code warning so an unattended outage leaves evidence even after
  recovery. Helper diagnostics expose only active/started/reaped/all-reaped and
  forced-kill facts; they never expose a PID, executable path or secret. The
  ARM64 helper also requests Linux parent-death termination so a Core crash
  cannot normally leave the native camera process running.
- The local brand art has not been submitted to Home Assistant Brands, so
  validation that requires the public Brands repository may remain pending.
- The documentation and issue URLs assume future publication at
  `ohlsont/ha-owlet-cam`.

## Troubleshooting

- A camera identifier begins with the letters `OC`, including known `OCA…` and
  `OCD…` forms. The first character is the letter `O`, not the digit `0`; the
  flow rejects that typo rather than silently changing it.
- Authentication errors can be corrected from the integration's reauthenticate
  action without creating a duplicate entry.
- Application and native-runtime problems appear as actionable Home Assistant
  Repairs. Open **Owlet Cam Runtime** as an administrator to upload a replacement
  package, rerun a bounded probe, restart the stream, or delete proprietary
  files. Upload filenames are ignored; supported formats are APK, APKM, XAPK
  and ZIP up to 512 MiB.
- The cloud probe requires an Owlet email/password login. If the account was
  created with Apple or Google sign-in, first verify that a typed Owlet password
  works in the official app; an active app session alone is not evidence that
  Firebase password authentication is available.
- If HACS cannot find the repository, confirm it is public and added as an
  Integration custom repository.
- Report warnings or lifecycle failures with redacted diagnostics. Never attach
  APK files, SDK keys, camera credentials, account passwords, or tokens.

The authoritative evidence ledger is [TEST_REPORT.md](TEST_REPORT.md).
