# Native probe build inputs

No compiled helper, Android runtime, Owlet application, proprietary library, or
SDK licence key belongs in this directory or in a HACS release archive.

The 2026-08-21 local ARM64 feasibility probe used:

- Debian 13.6 ARM64 container digest
  `sha256:1710bde34461551a19a47c787885ec9ad7058d9a5bead2affb8d088fa2f8502b`;
- AOSP `platform/prebuilts/runtime` commit
  `070571b455076f77a01c7b07154a15e545d2b428`;
- `com.android.runtime-arm64.apex` SHA-256
  `83bf0dce249728dae48149b80d28b48115c54adad95a352120d58a6ac669d1fc`;
- the APEX's ARM64 `linker64`, `libc.so`, `libdl.so`, and `libm.so` plus its
  licence notices;
- open-source Clang/LLD installed only in a disposable build container.

`helper/src/probe_libraries.c` is freestanding, has an explicit `_start`, loads
the user-supplied libraries with `dlopen`, emits JSON lines, closes every handle,
and exits. The local binary was an AArch64 PIE with the explicit interpreter
`/runtime/bin/linker64`. Its output is recorded in `TEST_REPORT.md`.

`helper/src/frame_probe.c` is a separate clean-room feasibility helper. It uses
the observed public/native ABI without proprietary headers, accepts all secret
material only in a single stdin JSON object, scrubs its fixed buffers, and emits
only fixed-schema connection/frame statistics. No compiled copy is committed.
The same source is compiled with `SNAPSHOT_CAPTURE` into a distinct helper that
stops after a decodable SPS/PPS/IDR access unit and writes those H.264 bytes only
to a validated inherited descriptor. No media is mixed with its JSON stdout.

For Milestone 6 the source is also compiled with `STREAM_CAPTURE`. That helper
keeps the single TUTK session open, writes each Annex-B access unit to stdout as
a four-byte big-endian length followed by media bytes, and reserves stderr for
one bounded, redacted lifecycle event. SIGTERM and SIGINT request native AV/IOTC
teardown before exit. Every helper mode requests Linux parent-death termination
before reading secrets and rejects launch when it has already lost its Home
Assistant parent. The Home Assistant process never loads the libraries.

When experimental local sensors are enabled, the stream helper also writes
fixed-size, big-endian telemetry records to a separately inherited descriptor.
Temperature is read from the camera's extended frame metadata; humidity, sound,
illuminance and Wi-Fi RSSI come from the observed bounded realtime-data control
exchange. Telemetry errors disable that side channel without stopping video or
audio, and the pipe carries no camera or account credentials.

`scripts/build_arm64_helper_in_container.sh` performs the complete reproducible
ARM64 build inside the pinned Debian image. It downloads the AOSP APEX only from
the pinned Android Git commit, verifies its SHA-256 before extraction, builds all
four clean-room helpers, and invokes `scripts/build_helper_runtime.py`. Two
independent Milestone 6 builds produced the same byte-for-byte archive.

`scripts/build_helper_runtime.py` now creates a deterministic `tar.gz` with a
per-file runtime manifest, the minimal open-source runtime, and complete AOSP
and integration licence notices. The helper and release workflows now run this
exact pinned build, package twice to require reproducibility, and inspect the
asset before upload. The first release-hosted download gate is still
unperformed. No asset may contain the user's application, ThroughTek/Owlet
libraries, SDK key, or camera credentials.
