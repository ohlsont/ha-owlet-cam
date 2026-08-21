# Owlet Cam for Home Assistant

Owlet Cam is a clean-room Home Assistant custom integration intended to expose
Owlet cameras as native camera and room-sensor entities. It is not affiliated
with, endorsed by, or supported by Owlet or ThroughTek.

## Current status: Milestone 1

Version `0.2.0` implements clean-room, asynchronous Owlet cloud authentication
and camera KMS validation. Embedded Experimental setup can validate a European
or World/US account and creates three native diagnostic entities without
starting native code:

- `binary_sensor.<camera>_cloud_reachable`
- `binary_sensor.<camera>_camera_credentials_available`
- `sensor.<camera>_authentication_expiry`

The credential-availability entity is boolean only. Firebase tokens, camera UID,
AuthKey, AV password, and account identifiers are not exposed in entity state,
attributes, diagnostics, logs, or frontend errors. Camera connection and media
are not implemented or claimed in this milestone.

External bridge mode is visible as the planned production fallback but is
explicitly unavailable until Milestone 2. No camera model or real account has
been tested yet. The user has deferred publishing the GitHub/HACS repository
until core functionality is further along, so Yellow real-account validation is
still unperformed.

## Planned runtime modes

- **External bridge** will be the first production-capable camera mode. It will
  connect to an independently running, known-compatible Owlet-to-RTSP bridge.
- **Embedded experimental** will use a separately supervised native helper. It
  will never load proprietary native libraries into Home Assistant's Python
  process, and users will supply their own application package.

External mode will remain available as a fallback after embedded mode exists.

## Supported installations

The minimum Home Assistant version is `2024.11.0`. Typed
`ConfigEntry.runtime_data` and reconfigure flows existed earlier, but 2024.11 is
the first release containing every reauth/reconfigure helper used by this
implementation, including `_get_reauth_entry`, `_get_reconfigure_entry`, and
the unique-ID mismatch guard.

The primary target is Home Assistant Yellow running Home Assistant OS on
AArch64. Milestone 0 contains pure Python only, but real Yellow validation has
not yet been performed. No architecture is claimed as hardware-tested.

## Install as a HACS custom repository

1. After this repository is published, in HACS open the custom repositories
   dialog.
2. Add `https://github.com/ohlsont/ha-owlet-cam` with category **Integration**.
3. Download **Owlet Cam** and restart Home Assistant.
4. Add **Owlet Cam** from Settings → Devices & services, choose **Embedded
   experimental**, and enter the Owlet account, region, printed camera DSN, and
   camera name.

The temporary Milestone 0 lifecycle mode remains hidden from ordinary setup and
is available only when Core starts with `OWLET_CAM_DEV_MODE=1`.

## Configuration and screenshots

Configuration, reauthentication, reconfiguration, and grouped general/embedded
options are implemented in the UI. Defaults favor stability and coexistence:
keep-warm, audio, direct-P2P preference, and experimental local sensors are all
off. Screenshots have not been captured because Yellow UI validation is
unperformed; fabricated screenshots are not included.

## Privacy and security

Account email and password live in Home Assistant config-entry data. Short-lived
Firebase and KMS camera credentials are kept only in memory. Private runtime
files will be kept
under `custom_components/owlet_cam/userfiles/`, which HACS preserves but Git and
release checks exclude. See [SECURITY.md](SECURITY.md).

## Known limitations

- No camera entity, bridge connection, native camera connection, snapshot, or
  stream.
- Cloud/KMS behavior has comprehensive sanitized fixture coverage but has not
  yet passed the real European account gate on the Yellow.
- No real Home Assistant Yellow or HACS installation evidence yet.
- The local brand art has not been submitted to Home Assistant Brands, so
  validation that requires the public Brands repository may remain pending.
- The documentation and issue URLs assume future publication at
  `ohlsont/ha-owlet-cam`.

## Troubleshooting

- A DSN begins with the letter `O` in `OCD`, not the digit `0`; the flow rejects
  the common typo rather than silently changing it.
- Authentication errors can be corrected from the integration's reauthenticate
  action without creating a duplicate entry.
- If HACS cannot find the repository, confirm it is public and added as an
  Integration custom repository.
- Report warnings or lifecycle failures with redacted diagnostics. Never attach
  APK files, SDK keys, camera credentials, account passwords, or tokens.

The authoritative evidence ledger is [TEST_REPORT.md](TEST_REPORT.md).
