# Security policy

This independent project is not affiliated with Owlet or ThroughTek.

## Security architecture

- Proprietary Owlet/ThroughTek libraries never load into the Home Assistant
  Core Python process. Embedded protocol work runs in a separately
  supervised child process with loopback-only control and media endpoints.
- The project does not ship Owlet applications, ThroughTek libraries, Owlet SDK
  keys, camera credentials, account credentials, or authentication tokens.
- Proprietary files are user-supplied and stored beneath
  `custom_components/owlet_cam/userfiles/` with restrictive permissions. The
  authenticated admin panel streams uploads to generated mode-0600 filenames;
  it never uses the submitted filename as a path. Extracted libraries are mode
  0500 and the SDK key is retained mode 0600 for archive-free restart recovery.
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

Open the administrator-only **Owlet Cam Runtime** panel and choose **Delete
proprietary files**. After explicit confirmation, the integration stops its
native producer and deletes uploaded application archives, extracted Owlet/
ThroughTek libraries, the stored SDK key, temporary extraction material and the
native-validation marker. The checksum-verified open-source helper runtime and
bounded logs remain. Removing the config entry separately deletes Home
Assistant's stored account configuration according to Home Assistant's normal
config-entry behavior.

By default the uploaded application archive is deleted immediately after a
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
