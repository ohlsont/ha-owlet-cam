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

These gates do not load a native library and do not prove that camera media is
available. A real probe still requires the user to place their own Owlet
application package in the ignored `userfiles/uploads/` directory. Account and
camera secrets will be accepted only through an interactive, non-echoing input
path and sent to the isolated helper over stdin; they must not be committed,
persisted, placed in environment variables, or logged.
