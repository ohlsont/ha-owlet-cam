# Reference versions

Inspected on **2026-08-21**; bridge API, audio and room-telemetry observations
were narrowly rechecked through **2026-08-27**.
Commit hashes were resolved from each repository's
default branch and the licence determination was made from files present at
that exact shallow checkout. No unlicensed implementation source was copied
into this repository.

| Repository | Commit | Commit date | Licence at commit | Files or observations used | Source copied | Clean-room notes |
|---|---|---:|---|---|---|---|
| `btoth525/Owlet-To-Rtsp` | `132620a85ff422b451e52fdbf2076abb3975e9ec` | 2026-08-12 | **No licence file found** | `native-bridge/bridge/owlet_api.py`, `webapp.py`, `native-bridge/docs/owlet-cam-sensors.md`, and `README.md`: observed the cloud/KMS sequence, bridge response shapes, extended-frame temperature field, and bounded realtime room-telemetry request/response ABI | No | Observations were reduced to independently written typed models, bounded HTTP/binary parsing, inherited-pipe framing, value gates, and hand-authored fixtures. The adapter ignores returned camera credentials. No expression, control flow, logging, threading model, or source was copied |
| `jquick/owlet-go` | `27142735e23d90d38d80d307e0c66294c61272d4` | 2026-07-13 | **No licence file found** | `README.md`, `Dockerfile`, `internal/tutk/`, `stream.go`, and `tools/`: observed the apkeep/SDK-key workflow, generic glibc Kalay library choice, native connection/AV lifecycle, raw H.264/AAC handling, single-session viewer sharing, reconnect behavior, and ARM64 container considerations | No | No source, headers, constants, or struct definitions were copied. Camera credential capture requires an installed interception CA and is excluded; the bundled third-party Kalay binary path is also excluded. Equivalent behavior must come from public SDK ABI material, independent observations, and our own tests |
| `AlexxIT/WebRTC` | `0c5421ba97ffa9a2458e0074466340ec411ac92b` | 2025-11-26 | MIT | Root `LICENSE`; lifecycle study deferred | No | Any later architectural observations will be documented independently |
| `AlexxIT/go2rtc` | `c245815e75e2a5fd60b4290f12bfc04e55a984d3` | 2026-07-13 | MIT | Root `LICENSE`; documented HTTP H.264, RTSP and WebRTC behavior was used only to evaluate Milestone 6 media boundaries | No | No go2rtc source or binary is included. The final implementation independently packages copied H.264 into timestamped MPEG-TS on a loopback HTTP URL and gives that supported source to Home Assistant's managed stream stack, avoiding a second process |
| `ryanbdclark/owlet` | `f8e0067a1e74a523b0bb4b0841b25404a6926ca8` | 2025-04-15 | Apache-2.0 | Root `LICENSE` and `README.md`; confirmed the separate Smart Sock integration/domain and HACS UI conventions | No | The `owlet` domain remains separate and is not modified or overridden |
| `EFForg/apkeep` | `0a60a4af03444ae237fa018848623ff9cd8b6119` | 2026-05-04 | MIT | Release 1.0.0 ARM64 binary and APKPure backend documentation; used only to download the user's application package without Google credentials | No | Release SHA-256 and William Budington's EFF-hosted signing key were independently verified before use |
| AOSP `platform/prebuilts/runtime` | `070571b455076f77a01c7b07154a15e545d2b428` | 2025-03-10 | Mixed permissive notices: Apache-2.0, BSD, ISC, MIT, legacy notice/unencumbered | `com.android.runtime-arm64.apex` blob `26a7749e9b232184112897144c97128073776f2a`; Bionic `linker64`, `libc.so`, `libdl.so`, and `libm.so` used for an isolated local load probe | No | Open-source runtime artefacts were downloaded to temporary storage only and are not committed or bundled |

`Owlet-To-Rtsp` and `owlet-go` had no file matching `LICENSE`, `COPYING`, or
`NOTICE` anywhere in the inspected checkout. The absence of a licence means no
permission to copy implementation code is assumed.

At the inspected `owlet-go` commit, its documented credential workflow installs
a locally generated interception CA on the phone, and its tree contains the
capture CA certificate and private key. Its Docker build downloads a generic
ThroughTek shared object from another repository rather than using libraries
from the user's Owlet application. Neither mechanism is used by this project.

On 2026-08-26, the pinned `jquick/owlet-go` revision was re-inspected narrowly
for incoming-audio observations. It independently identifies an audio-start
control followed by `avRecvAudioData`, and treats the resulting access units as
AAC-LC at 8 kHz mono. ThroughTek's public Kalay documentation independently
confirms that audio is received from the AV channel through a separate
`avRecvAudioData` loop and defines the public codec IDs for raw AAC (`0x86`),
ADTS AAC (`0x87`) and LATM AAC (`0x88`). FFmpeg's public MPEG-TS definitions
identify AAC stream type `0x0f`. No source, header, control flow, or struct
definition was copied from the unlicensed reference project; the helper ABI,
separate inherited-pipe framing, ADTS construction, MPEG-TS packetizer and
tests were independently written in this repository.

The 2026-08-26 Yellow probe added independent real-device evidence: the Owlet
Cam 1 reported public Kalay codec ID `0x88`, while the received access units
already carried ADTS sync and configuration. The clean-room adapter therefore
preserves detected ADTS and LOAS framing and adds ADTS only to genuinely bare
AAC access units. FFprobe then identified AAC-LC, 8000 Hz, mono. No audio bytes
were stored in diagnostics or copied from a reference implementation.

Milestone 1 additionally used Google's public Firebase Auth REST documentation
to independently implement password authentication, token expiry parsing, and
refresh behavior using the documented
`identitytoolkit.googleapis.com/v1/accounts:signInWithPassword` endpoint. No
reference implementation was copied. Firebase project/API identifiers and
Android package/cert identifiers are application identity metadata, not Owlet
account credentials or the prohibited Kalay SDK licence key. Actual Firebase,
KMS, UID, AuthKey, and AV password values are never persisted outside Home
Assistant's configured account credentials and the integration process's
private memory.

The signed `com.owletcare.sleep` version 3.36.0 package supplied by the user was
also inspected locally with Androguard. Its manifest and certificate establish
the Dream application's identity, while its constructed Firebase options
confirm the separate `owletcare-prod` and `owletcare-prod-eu` Auth projects and
their public application identifiers. A narrow URL-construction observation
also established that the Europe environment inserts `.eu` into the camera KMS
hostname. A second narrow inspection established that Dream passes its internal
camera `dsn` unchanged to this URL with the raw, fresh Firebase token and only
generic app/version user-agent and language headers; it does not add an App
Check token or another KMS authorization value. These public configuration and
protocol facts selected the Dream identity, Firebase application-ID header,
region-specific KMS URL, and independently implemented request contract. No
decompiled expression or control flow was copied. No user credential, camera
credential, SDK key, or proprietary application file was copied into the
repository.

The same narrow annotation inspection identified the Dream Accounts API's
read-only `GET v2/accounts/{accountId}` and
`GET v2/accounts/{accountId}/devices` contracts. They were used only for a
redacted account/device-mapping comparison that emitted status codes, counts,
and equality booleans. No response model, expression, implementation flow, or
account/device value was copied or retained.

The local native feasibility probe used apkeep as an external acquisition tool,
not as source code. Its ARM64 release binary had SHA-256
`5410acebd1b69427adcf98ccfdda6fa4dd3201e0540e5e2c01037b68e0a84049`
and a valid OpenPGP signature from EFF key fingerprint
`1073 E74E B38B D6D1 9476 CBF8 EA9D BF9F B761 A677`. The pinned AOSP ARM64
runtime APEX had SHA-256
`83bf0dce249728dae48149b80d28b48115c54adad95a352120d58a6ac669d1fc`.

On 2026-08-22, the user installed the official Dream 3.40.0 (`64832`) Google
Play build on a clean Android 15 ARM64 emulator. Narrow inspection of that
user-supplied package established only protocol/ABI observations needed for an
independent implementation: Firebase UID selects the Firestore account; direct
account/service/device references lead to the internal KMS DSN; connection uses
AuthKey authentication with a 20-second bound; AV authentication uses account
`admin`, password mode, automatic security, resend enabled, and the documented
DTLS cipher policy. The app also established the exact native input/output
structure sizes and initialization parameters used by its wrapper. No
decompiled expression, control flow, identifier, credential, SDK key, Java/Kotlin
source, native library, or application file was copied into this repository.
`helper/src/frame_probe.c` was independently written with fixed byte layouts and
tests against the user-owned binary behavior.
