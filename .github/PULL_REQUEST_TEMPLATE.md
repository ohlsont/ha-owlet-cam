## Summary

Describe the user-visible change and its scope.

## Validation

List automated tests and real-system evidence actually performed. Mark anything
unperformed explicitly.

## Checklist

- [ ] I ran the relevant Ruff, mypy, pytest, release, and secret checks.
- [ ] I added or updated tests for changed behavior.
- [ ] I updated `CHANGELOG.md`, `README.md`, and `TEST_REPORT.md` when the change affects users or evidence.
- [ ] I did not add an APK/APKM/XAPK, Owlet/ThroughTek library, SDK key, credential, token, camera identifier, private key, local runtime data, image, or video.
- [ ] Reverse-engineered observations are documented as clean-room facts; no unlicensed or decompiled implementation source was copied.
- [ ] Diagnostics, logs, exceptions, commands, URLs, fixtures, and screenshots contain no secrets or personal identifiers.
- [ ] I have not claimed an unperformed real-camera, outage, soak, architecture, or compatibility test as passed.
