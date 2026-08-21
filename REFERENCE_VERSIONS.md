# Reference versions

Inspected on **2026-08-21**. Commit hashes were resolved from each repository's
default branch and the licence determination was made from files present at
that exact shallow checkout. No implementation source was copied into this
repository for Milestone 0.

| Repository | Commit | Commit date | Licence at commit | Files or observations used | Source copied | Clean-room notes |
|---|---|---:|---|---|---|---|
| `btoth525/Owlet-To-Rtsp` | `132620a85ff422b451e52fdbf2076abb3975e9ec` | 2026-08-12 | **No licence file found** | `native-bridge/bridge/owlet_api.py` and `native-bridge/README.md`: observed the Firebase email/password → raw ID token → camera KMS sequence, region-specific Firebase projects, Android identity headers, KMS status behavior, and credential field names | No | Observations were reduced to an independently written HTTP contract and hand-authored fixtures; no expressions, control flow, logging, or source were copied |
| `jquick/owlet-go` | `27142735e23d90d38d80d307e0c66294c61272d4` | 2026-07-13 | **No licence file found** | Repository layout and README presence only; native study deferred | No | Treat all implementation as unavailable for copying; future work may record observations only |
| `AlexxIT/WebRTC` | `0c5421ba97ffa9a2458e0074466340ec411ac92b` | 2025-11-26 | MIT | Root `LICENSE`; lifecycle study deferred | No | Any later architectural observations will be documented independently |
| `AlexxIT/go2rtc` | `c245815e75e2a5fd60b4290f12bfc04e55a984d3` | 2026-07-13 | MIT | Root `LICENSE`; distribution study deferred | No | Any later use must preserve notices and pin an exact released asset |
| `ryanbdclark/owlet` | `f8e0067a1e74a523b0bb4b0841b25404a6926ca8` | 2025-04-15 | Apache-2.0 | Root `LICENSE` and `README.md`; confirmed the separate Smart Sock integration/domain and HACS UI conventions | No | The `owlet` domain remains separate and is not modified or overridden |

`Owlet-To-Rtsp` and `owlet-go` had no file matching `LICENSE`, `COPYING`, or
`NOTICE` anywhere in the inspected checkout. The absence of a licence means no
permission to copy implementation code is assumed.

Milestone 1 additionally used Google's public Firebase Auth REST documentation
to independently implement `accounts:signInWithPassword`, token expiry parsing,
and refresh behavior. Firebase project/API identifiers and Android package/cert
identifiers are application identity metadata, not Owlet account credentials or
the prohibited Kalay SDK licence key. Actual Firebase, KMS, UID, AuthKey, and AV
password values are never persisted outside Home Assistant's configured account
credentials and the integration process's private memory.
