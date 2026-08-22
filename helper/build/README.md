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

`scripts/build_helper_runtime.py` now creates a deterministic `tar.gz` with a
per-file runtime manifest, the minimal open-source runtime, and complete AOSP
and integration licence notices. Its output is a local test artefact until the
same build is wired into the release workflow and the Yellow gate passes. No
asset may contain the user's application, ThroughTek/Owlet libraries, SDK key,
or camera credentials.
