# Safe beta testing checklist

This checklist gathers useful compatibility evidence without asking testers to
weaken Home Assistant security or disclose private material. Partial and failed
results are valuable; never mark an unperformed step as passed.

## Safety first

- Use a camera and Owlet account you are authorized to access.
- Back up Home Assistant before installation or upgrade.
- Confirm the official Dream/Owlet application can show the camera before
  diagnosing this integration.
- Obtain application material legitimately and prepare the private `.owletcam`
  package on a desktop as described in the README.
- Do not install a capture certificate, enable privileged mode, expose Docker or
  host PID/IPC, weaken AppArmor, or expose an internal media port to the LAN.
- Never publish an APK/APKM/XAPK, `.owletcam` package, native library, SDK key,
  password, token, UID, AuthKey, AV password, camera serial/DSN, MAC address,
  private camera image/video, or local path containing a user name.

## Environment record

Record only:

- Owlet Cam integration version.
- Home Assistant Core and OS/container versions.
- HACS version and machine architecture.
- Camera model and firmware when known, without its identifier.
- Account region: Europe/EMEA or World/US.
- Embedded or external-bridge mode.

## Installation and lifecycle

1. Add `https://github.com/ohlsont/ha-owlet-cam` as a HACS custom repository of
   category **Integration**.
2. Install the latest release and restart Home Assistant when HACS requests it.
3. Confirm **Owlet Cam** appears under Add integration.
4. Complete the UI config flow and confirm only one device/entity set appears.
5. Reload the entry once and confirm entities return without duplicates.
6. After any restart, confirm the entry returns to `loaded` and Home Assistant
   remains responsive.

## Embedded runtime and media

Perform only the steps you are comfortable with:

1. Confirm **Runtime status** becomes `ready`, **Helper version** matches the
   integration, and **Native libraries compatible** is on.
2. Request a snapshot and confirm it is current. Do not attach the image to a
   report.
3. Open live view and record only codec, resolution, FPS, startup time and
   whether video changes normally.
4. If audio is enabled, record whether it is audible and the safe Audio
   status/codec values. Do not record or upload room audio.
5. Open a second Home Assistant viewer if practical and confirm it does not
   create a duplicate entity or camera session.
6. Close viewers and confirm the stream returns to idle after the configured
   timeout.
7. Confirm the official app can reconnect after Home Assistant becomes idle.

Physical power, Wi-Fi and internet interruption tests are optional and require
the owner's participation. Do not perform them merely to complete a report.

## Diagnostics and reporting

1. Check Home Assistant Repairs and note only safe issue codes.
2. Download Owlet Cam diagnostics, inspect the complete file locally and verify
   that account/camera identifiers and credentials are shown only as redacted.
3. Remove unexpected URLs, local paths, identifiers or private values before
   attaching diagnostics.
4. Use the repository's **Beta compatibility report** issue form. Mark every
   item pass, fail or unperformed.
5. Use private vulnerability reporting rather than an issue if redaction or
   secret handling fails.

The integration has no telemetry and cannot upload a report automatically.
