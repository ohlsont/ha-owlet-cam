# Owlet Cam helper

This directory is source/build infrastructure for the isolated native helper.
Compiled helpers must be produced as versioned release assets and must
never include Owlet applications, proprietary libraries, SDK keys, or
camera/account credentials.

The `probe/local-video` feasibility branch begins with two pure-Python gates in
`custom_components/owlet_cam/runtime/`:

- allowlisted, size-bounded APK/APKM/XAPK/ZIP extraction with nested split APK,
  zip-slip and special-file protection;
- dependency-free ELF64 inspection for AArch64, dynamic dependencies, exported
  symbols and writable-executable segments.

The local feasibility branch also contains freestanding Bionic library, frame,
and snapshot-capture probe modes. With user-supplied, validly signed Owlet
3.36.0 and 3.40.0 ARM64 bundles,
the no-camera helper loaded and closed all five required native libraries in a
network-disabled Linux/ARM64 container using a pinned AOSP Bionic runtime.

After authorized camera discovery and KMS lookup succeeded, the clean-room frame
helper received 100 real H.264 frames in each of three isolated Android 15 ARM64
emulator runs. Each contained SPS, PPS and IDR NALs, parsed as 1920×1080, and
reported clean shutdown. The runner removed the fixed emulator temporary
directory after every run. Docker/OrbStack IOTC attempts timed out. The runtime
and frame helpers subsequently passed their bounded Yellow gates inside Home
Assistant Core; the snapshot helper has not yet run there.

The rebuilt library and frame helpers have also passed those emulator gates.
The snapshot mode is compiled separately from the same clean-room source and
writes media only to an inherited descriptor supplied by the supervising Core
process; stdout remains fixed-schema, non-secret JSON.
`scripts/build_helper_runtime.py` packages them with only the pinned minimal
AOSP Bionic files and licence notices, emits a per-file checksum manifest, and
produces deterministic output. The resulting archive remains a local test
artefact until Yellow validation and release hosting are complete.

Home Assistant account credentials remain in config-entry data. Short-lived
camera credentials and the user-extracted SDK key are sent to the isolated
helper over stdin only; they must not be committed, persisted to runtime files,
placed in environment variables or command arguments, or logged.
