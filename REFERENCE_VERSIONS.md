# Reference versions

Inspected on **2026-08-21**. Commit hashes were resolved from each repository's
default branch and the licence determination was made from files present at
that exact shallow checkout. No implementation source was copied into this
repository for Milestone 0.

| Repository | Commit | Commit date | Licence at commit | Files or observations used | Source copied | Clean-room notes |
|---|---|---:|---|---|---|---|
| `btoth525/Owlet-To-Rtsp` | `132620a85ff422b451e52fdbf2076abb3975e9ec` | 2026-08-12 | **No licence file found** | `native-bridge/bridge/owlet_api.py` and `native-bridge/README.md`: observed the Firebase email/password → raw ID token → camera KMS sequence, region-specific Firebase projects, Android identity headers, KMS status behavior, and credential field names | No | Observations were reduced to an independently written HTTP contract and hand-authored fixtures; no expressions, control flow, logging, or source were copied |
| `jquick/owlet-go` | `27142735e23d90d38d80d307e0c66294c61272d4` | 2026-07-13 | **No licence file found** | `README.md`, `Dockerfile`, `internal/tutk/`, `stream.go`, and `tools/`: observed the apkeep/SDK-key workflow, generic glibc Kalay library choice, native connection/AV lifecycle, raw H.264/AAC handling, single-session viewer sharing, reconnect behavior, and ARM64 container considerations | No | No source, headers, constants, or struct definitions were copied. Camera credential capture requires an installed interception CA and is excluded; the bundled third-party Kalay binary path is also excluded. Equivalent behavior must come from public SDK ABI material, independent observations, and our own tests |
| `AlexxIT/WebRTC` | `0c5421ba97ffa9a2458e0074466340ec411ac92b` | 2025-11-26 | MIT | Root `LICENSE`; lifecycle study deferred | No | Any later architectural observations will be documented independently |
| `AlexxIT/go2rtc` | `c245815e75e2a5fd60b4290f12bfc04e55a984d3` | 2026-07-13 | MIT | Root `LICENSE`; distribution study deferred | No | Any later use must preserve notices and pin an exact released asset |
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
the Android application identity, while its constructed Firebase options
identify the separate `owletcare-prod` and `owletcare-prod-eu` Auth projects.
Only those public configuration facts were recorded; no decompiled expression
or control flow was copied. No user credential, camera credential, SDK key, or
proprietary application file was copied into the repository.

The local native feasibility probe used apkeep as an external acquisition tool,
not as source code. Its ARM64 release binary had SHA-256
`5410acebd1b69427adcf98ccfdda6fa4dd3201e0540e5e2c01037b68e0a84049`
and a valid OpenPGP signature from EFF key fingerprint
`1073 E74E B38B D6D1 9476 CBF8 EA9D BF9F B761 A677`. The pinned AOSP ARM64
runtime APEX had SHA-256
`83bf0dce249728dae48149b80d28b48115c54adad95a352120d58a6ac669d1fc`.
