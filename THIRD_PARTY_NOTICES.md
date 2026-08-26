# Third-party notices and licence scope

The MIT licence in [LICENSE](LICENSE) applies to the original clean-room source,
documentation, tests, workflows, and project artwork in this repository unless
a file states otherwise.

It does not grant rights to proprietary material supplied by a user, including:

- Owlet application packages or application content;
- Owlet or ThroughTek native libraries;
- Owlet/Kalay SDK licence keys;
- camera UID, AuthKey, AV password, account credentials, or tokens.

Those files are not part of this repository or its release archives. They remain
subject to the rights and terms of their respective owners.

## Helper runtime assets

Separately published helper runtime assets may contain a minimal set of
open-source Android Bionic runtime components. Each helper asset includes:

- `LICENSES/AOSP-NOTICE.html.gz`, containing the applicable Android Open Source
  Project licence and attribution notices;
- `LICENSES/OWLET-CAM-MIT.txt`, containing this project's MIT licence; and
- a runtime manifest identifying the pinned AOSP source commit and confirming
  that the asset contains no proprietary files.

The project release workflow also generates an SPDX SBOM and licence manifest.
The third-party components remain under their own licences; the repository's
MIT licence does not replace or modify those terms.

## Reference implementations

Public projects used for architectural or protocol research, their exact
commits, licences, copied-source status, and clean-room notes are recorded in
[REFERENCE_VERSIONS.md](REFERENCE_VERSIONS.md). No licence is inferred for an
unlicensed reference repository, and its implementation source is not copied.

## Trademarks

Owlet, ThroughTek, Kalay, Android, Home Assistant, HACS, and other product names
and marks belong to their respective owners. The project licence does not grant
trademark rights or imply affiliation, endorsement, or support.
