# Owlet Cam for Home Assistant

Owlet Cam is a clean-room Home Assistant custom integration intended to expose
Owlet cameras as native camera and room-sensor entities. It is not affiliated
with, endorsed by, or supported by Owlet or ThroughTek.

## Current status: Yellow frame and Dream coexistence gate passed

Version `0.2.0` implements clean-room, asynchronous Owlet cloud authentication
and camera KMS validation. Embedded Experimental setup can validate a European
or World/US account. The production cloud client follows authorized Firestore
account → service → device references when a Cam 1's app-visible serial differs
from its internal KMS DSN; that internal value is kept in memory only.

The integration creates cloud diagnostics plus cached experimental runtime
diagnostics. Native work starts only after the disabled-by-default **Run runtime
probe** button is explicitly enabled and pressed. A separately supervised child
process receives secrets through stdin only; config-entry unload terminates its
process group and scrubs the cached SDK key.

Core cloud entities include:

- `binary_sensor.<camera>_cloud_reachable`
- `binary_sensor.<camera>_camera_credentials_available`
- `sensor.<camera>_authentication_expiry`

The credential-availability entity is boolean only. Firebase tokens, camera UID,
AuthKey, AV password, and account identifiers are not exposed in entity state,
attributes, diagnostics, logs, or frontend errors.

External bridge mode is visible as the planned production fallback but is
explicitly unavailable until Milestone 2. A redacted real-account probe has
authenticated successfully against the user-confirmed EMEA project. Direct
authorized Firestore account → service → device references resolved one
internal camera DSN; that value differs from the identifier Dream displays to
the user. Regional KMS validation using the internal DSN succeeded and emitted
only credential-presence booleans. No account, device, token, DSN, UID, AuthKey,
AV password, or SDK key value was retained or displayed. This discovery path is
now used by the Home Assistant client and config flow.
The user has deferred publishing the GitHub/HACS repository until core
functionality is further along. A private manual Yellow installation now proves
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
reclaimed live video afterward. The camera entity claims no stream feature.
Direct process enumeration inside the Core PID namespace remains unperformed:
the supported SSH add-on cannot see that namespace, and no host-PID, Docker or
privileged workaround was enabled.

A deterministic package script now creates a checksum-manifested ARM64 runtime
containing only the three clean-room helpers, a minimal pinned AOSP Bionic runtime,
and licence notices. The current local archive was scanned against configured
secrets and common token patterns; no user application or proprietary library
is included. It remains a local test artefact until the Yellow gate passes and
release hosting is enabled.

## Planned runtime modes

- **External bridge** will be the first production-capable camera mode. It will
  connect to an independently running, known-compatible Owlet-to-RTSP bridge.
- **Embedded experimental** will use a separately supervised native helper. It
  will never load proprietary native libraries into Home Assistant's Python
  process, and users will supply their own application package.

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

1. After this repository is published, in HACS open the custom repositories
   dialog.
2. Add `https://github.com/ohlsont/ha-owlet-cam` with category **Integration**.
3. Download **Owlet Cam** and restart Home Assistant.
4. Add **Owlet Cam** from Settings → Devices & services, choose **Embedded
   experimental**, and enter the Owlet account, region, camera serial, and camera
   name. The serial shown in Dream is accepted even when Owlet uses a different
   internal KMS identifier.

The temporary Milestone 0 lifecycle mode remains hidden from ordinary setup and
is available only when Core starts with `OWLET_CAM_DEV_MODE=1`.

## Configuration and screenshots

Configuration, reauthentication, reconfiguration, and grouped general/embedded
options are implemented in the UI. Defaults favor stability and coexistence:
keep-warm, audio, direct-P2P preference, and experimental local sensors are all
off. Screenshots have not been captured because Yellow UI validation is
unperformed; fabricated screenshots are not included.

## Privacy and security

Account email and password live in Home Assistant config-entry data. Short-lived
Firebase and KMS camera credentials are kept only in memory. Private runtime
files will be kept
under `custom_components/owlet_cam/userfiles/`, which HACS preserves but Git and
release checks exclude. See [SECURITY.md](SECURITY.md).

## Known limitations

- The embedded snapshot-only camera and standard `camera.snapshot` service have
  passed their real JPEG, concurrency, periodic-soak and official-app recovery
  gates on Yellow. There is no bridge connection, RTSP source, or continuous
  Home Assistant stream.
- Cloud/KMS behavior has comprehensive sanitized fixture coverage and succeeded
  inside Home Assistant Core on Yellow. Wrong-password reauthentication and the
  complete Milestone 1 acceptance sequence remain unperformed.
- Manual Yellow installation is proven; HACS installation is not. The initial
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
- The cloud probe requires an Owlet email/password login. If the account was
  created with Apple or Google sign-in, first verify that a typed Owlet password
  works in the official app; an active app session alone is not evidence that
  Firebase password authentication is available.
- If HACS cannot find the repository, confirm it is public and added as an
  Integration custom repository.
- Report warnings or lifecycle failures with redacted diagnostics. Never attach
  APK files, SDK keys, camera credentials, account passwords, or tokens.

The authoritative evidence ledger is [TEST_REPORT.md](TEST_REPORT.md).
