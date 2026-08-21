# Owlet Cam helper

This directory is source/build infrastructure for the future isolated native
helper. Compiled helpers must be produced as versioned release assets and must
never include Owlet applications, proprietary libraries, SDK keys, or
camera/account credentials.

The `probe/local-video` feasibility branch begins with two pure-Python gates in
`custom_components/owlet_cam/runtime/`:

- allowlisted, size-bounded APK/APKM/XAPK/ZIP extraction with nested split APK,
  zip-slip and special-file protection;
- dependency-free ELF64 inspection for AArch64, dynamic dependencies, exported
  symbols and writable-executable segments.

The local feasibility branch now also contains a freestanding no-camera Bionic
loader probe. With a user-supplied, validly signed Owlet 3.36.0 ARM64 bundle, it
loaded and closed all five required native libraries in a network-disabled
Linux/ARM64 container using a pinned AOSP Bionic runtime. This is not camera or
media evidence; real KMS handoff, camera connection, and H.264 receipt remain
unperformed.

Account and camera secrets will be accepted only through an interactive,
non-echoing input path and sent to the isolated helper over stdin; they must not
be committed, persisted, placed in environment variables, or logged.
