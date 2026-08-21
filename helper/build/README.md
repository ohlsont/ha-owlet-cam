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

This manual spike must become a pinned, checksummed GitHub Actions build before
any embedded runtime is distributed. A release asset may contain our helper,
the minimal open-source runtime, and complete licence notices, but never the
user's application, ThroughTek/Owlet libraries, SDK key, or camera credentials.
