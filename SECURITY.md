# Security policy

This independent project is not affiliated with Owlet or ThroughTek.

## Security architecture

- Proprietary Owlet/ThroughTek libraries never load into the Home Assistant
  Core Python process. Embedded protocol work runs in a separately
  supervised child process with loopback-only control and media endpoints.
- The project does not ship Owlet applications, ThroughTek libraries, Owlet SDK
  keys, camera credentials, account credentials, or authentication tokens.
- The desktop preparer accepts an existing application, exports installed splits
  with adb, or optionally invokes apkeep. The apkeep path accepts only a private
  configuration-file path; Google email/auth tokens are never put in preparer
  command arguments, output, the `.owletcam` package, or Home Assistant.
- The preparer is a dependency-free Python zipapp published as a checksummed
  release asset. Its deterministic source archive is inspected by CI and can be
  reproduced from `scripts/build_preparer_zipapp.py`.
- A `.owletcam` package contains only the user's five required ARM64 libraries,
  SDK key and integrity metadata. It is mode 0600, must not be shared, and is
  independently subjected to a fixed-member allowlist, size/hash checks and the
  normal ELF/symbol gates after upload.
- Proprietary files are user-supplied and stored beneath
  `custom_components/owlet_cam/userfiles/` with restrictive permissions. The
  embedded setup and Reconfigure flows use Home Assistant's authenticated native
  file-upload service, then copy into generated mode-0600 filenames; they never
  use the submitted filename as a path. Extracted libraries are mode 0500 and
  the SDK key is retained mode 0600 for archive-free restart recovery.
- Account and external-bridge credentials belong in Home Assistant config-entry
  storage. Firebase and KMS tokens remain in memory. Secrets are not passed as command
  arguments or environment variables to helper processes.
- Open-source helper assets are fetched only from this repository's exact
  `v<integration-version>` GitHub release. The architecture-specific filename
  and checksum entry must be unique, the download streams to a private bounded
  temporary file, SHA-256 plus runtime version/architecture and every internal
  file checksum are verified, and only then is installation replaced atomically.
- The current external bridge's camera-list response contains UID/AuthKey and
  password fields. The integration's parser deliberately ignores them; typed
  bridge models, entities and diagnostics contain no such fields. Optional
  explicit RTSP URLs are redacted because users may put credentials in them.
- Helper processes run in their own process group, are synchronously reaped on
  stop, and request Linux parent-death termination before reading secrets.
  Diagnostics expose only aggregate lifecycle facts and fixed safe error codes;
  they never expose PIDs, executable paths, media URLs or credentials.

No certificate authority, traffic interception, privileged container access,
Docker socket, AppArmor relaxation, host PID/IPC access, or LAN listener is part
of the supported design.

## Deleting stored material

Open Settings → Devices & services → Owlet Cam, choose **Reconfigure**, select
**Delete all stored proprietary files**, and complete the separate confirmation
step. The integration stops its native producer and deletes uploaded packages,
extracted Owlet/ThroughTek libraries, the stored SDK key, temporary extraction
material and the native-validation marker. The checksum-verified open-source
helper runtime and bounded logs remain. Removing the config entry separately deletes Home
Assistant's stored account configuration according to Home Assistant's normal
config-entry behavior.

By default the uploaded runtime package or application archive is deleted immediately after a
successful extraction/library probe. The embedded option **Retain uploaded
application after extraction** can keep it. Firebase, KMS UID/AuthKey/AV
password material and tokens remain memory-only and are never written to
`userfiles`.

## Reporting a vulnerability

Use the repository's private GitHub security advisory flow. Do not include live
credentials, tokens, APKs, SDK keys, camera UIDs, AuthKeys, AV passwords, or
private video. Provide sanitized reproduction steps and the integration/Home
Assistant versions. Public issues are appropriate only after secrets and
personally identifying data have been removed.
