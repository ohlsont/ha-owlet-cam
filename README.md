# Owlet Cam for Home Assistant

Owlet Cam is a clean-room Home Assistant custom integration intended to expose
Owlet cameras as native camera and room-sensor entities. It is not affiliated
with, endorsed by, or supported by Owlet or ThroughTek.

## Current status: Milestone 0

Version `0.1.0` proves the HACS repository layout and Home Assistant config-entry
lifecycle. It performs **no Owlet networking** and creates only
`sensor.owlet_cam_integration_status`. The temporary setup flow is hidden unless
the Home Assistant Core process starts with `OWLET_CAM_DEV_MODE=1`.

External bridge mode and embedded experimental mode are designed but are not
implemented or claimed to work in this milestone. No camera model has been
tested yet. ARM64/Yellow validation is explicitly unperformed until the files
can be installed on the target system.

## Planned runtime modes

- **External bridge** will be the first production-capable camera mode. It will
  connect to an independently running, known-compatible Owlet-to-RTSP bridge.
- **Embedded experimental** will use a separately supervised native helper. It
  will never load proprietary native libraries into Home Assistant's Python
  process, and users will supply their own application package.

External mode will remain available as a fallback after embedded mode exists.

## Supported installations

The minimum Home Assistant version is `2024.5.0`, the first monthly release
after `ConfigEntry.runtime_data` was documented on 2024-04-30. This repository
uses that API for typed lifecycle state. HACS itself currently requires at
least Home Assistant 2024.4.1.

The primary target is Home Assistant Yellow running Home Assistant OS on
AArch64. Milestone 0 contains pure Python only, but real Yellow validation has
not yet been performed. No architecture is claimed as hardware-tested.

## Install as a HACS custom repository

1. In HACS, open the custom repositories dialog.
2. Add this repository URL with category **Integration**.
3. Download **Owlet Cam** and restart Home Assistant.
4. For Milestone 0 development validation only, start Core with
   `OWLET_CAM_DEV_MODE=1`, then add **Owlet Cam** from Settings → Devices &
   services.

The environment switch is intentionally absent from ordinary user operation.
Do not enable it as a substitute for a camera integration.

## Configuration and screenshots

There is no production configuration in Milestone 0. UI configuration,
reauthentication, reconfiguration, and options arrive in their gated
milestones. Screenshots have not been captured because Yellow UI validation is
unperformed; fabricated screenshots are not included.

## Privacy and security

Milestone 0 makes no network requests and stores no credentials. Future account
credentials will live in Home Assistant config-entry data, while short-lived
cloud and KMS tokens will be kept in memory. Private runtime files will be kept
under `custom_components/owlet_cam/userfiles/`, which HACS preserves but Git and
release checks exclude. See [SECURITY.md](SECURITY.md).

## Known limitations

- No camera, cloud authentication, KMS lookup, bridge connection, or media.
- No real Home Assistant Yellow or HACS installation evidence yet.
- The local brand art has not been submitted to Home Assistant Brands, so
  validation that requires the public Brands repository may remain pending.
- The documentation and issue URLs assume publication at
  `tomasohlson/ha-owlet-cam`.

## Troubleshooting

- If setup immediately says development is disabled, that is expected unless
  Core was started with `OWLET_CAM_DEV_MODE=1`.
- If HACS cannot find the repository, confirm it is public and added as an
  Integration custom repository.
- Report warnings or lifecycle failures with redacted diagnostics. Never attach
  APK files, SDK keys, camera credentials, account passwords, or tokens.

The authoritative evidence ledger is [TEST_REPORT.md](TEST_REPORT.md).
