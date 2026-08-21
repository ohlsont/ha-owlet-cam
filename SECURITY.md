# Security policy

This independent project is not affiliated with Owlet or ThroughTek.

## Security architecture

- Proprietary Owlet/ThroughTek libraries will never load into the Home
  Assistant Core Python process. Embedded protocol work will run in a separately
  supervised child process with loopback-only control and media endpoints.
- The project will not ship Owlet applications, ThroughTek libraries, Owlet SDK
  keys, camera credentials, account credentials, or authentication tokens.
- Proprietary files will be user-supplied and, when implemented, stored beneath
  `custom_components/owlet_cam/userfiles/` with restrictive permissions.
- Account credentials belong in Home Assistant config-entry storage. Firebase
  and KMS tokens should remain in memory. Secrets will not be passed as command
  arguments or environment variables to helper processes.
- Downloaded open-source helper assets will be version-pinned and SHA-256
  verified before atomic installation.

No certificate authority, traffic interception, privileged container access,
Docker socket, AppArmor relaxation, host PID/IPC access, or LAN listener is part
of the supported design.

## Deleting stored material

Milestone 0 stores no proprietary material. Before the authenticated delete UI
exists, a user may stop/unload the integration and remove the contents of
`custom_components/owlet_cam/userfiles/` using an existing Home Assistant file
management method. Do not delete the integration directory while Home Assistant
is running.

## Reporting a vulnerability

Use the repository's private GitHub security advisory flow. Do not include live
credentials, tokens, APKs, SDK keys, camera UIDs, AuthKeys, AV passwords, or
private video. Provide sanitized reproduction steps and the integration/Home
Assistant versions. Public issues are appropriate only after secrets and
personally identifying data have been removed.
