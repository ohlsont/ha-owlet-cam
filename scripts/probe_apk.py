#!/usr/bin/env python3
"""Safely extract and report on a user-supplied Owlet application bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.owlet_cam.runtime.apk import (  # noqa: E402
    extract_owlet_application,
)
from custom_components.owlet_cam.runtime.elf import inspect_elf  # noqa: E402

REQUIRED_SYMBOLS: Final[dict[str, frozenset[str]]] = {
    "libAVAPIs.so": frozenset(
        {
            "avClientStartEx",
            "avClientStop",
            "avDeInitialize",
            "avInitialize",
            "avRecvFrameData2",
            "avSendIOCtrl",
        }
    ),
    "libIOTCAPIs.so": frozenset(
        {
            "IOTC_Connect_ByUIDEx",
            "IOTC_DeInitialize",
            "IOTC_Get_SessionID",
            "IOTC_Initialize2",
            "IOTC_Session_Close",
        }
    ),
    "libP2PTunnelAPIs.so": frozenset(),
    "libRDTAPIs.so": frozenset(),
    "libTUTKGlobalAPIs.so": frozenset(
        {
            "TUTK_SDK_Set_License_Key",
            "TUTK_SDK_Set_Region",
        }
    ),
}


def build_report(archive: Path, destination: Path) -> dict[str, object]:
    """Return a redacted structural report; never serialize the SDK key."""
    application = extract_owlet_application(archive, destination)
    libraries: list[dict[str, object]] = []
    for name, library in application.libraries.items():
        elf = inspect_elf(
            library.path,
            required_symbols=REQUIRED_SYMBOLS.get(name, frozenset()),
        )
        libraries.append(
            {
                "name": name,
                "sha256": library.sha256,
                "size": library.size,
                "architecture": elf.architecture,
                "elf_class": elf.elf_class,
                "little_endian": elf.little_endian,
                "interpreter": elf.interpreter,
                "dependencies": elf.dependencies,
                "required_symbols_present": elf.required_symbols_present,
                "missing_required_symbols": elf.missing_required_symbols,
                "has_writable_executable_segment": (
                    elf.has_writable_executable_segment
                ),
            }
        )
    return {
        "source_sha256": application.source_sha256,
        "abi": application.abi,
        "libraries": libraries,
        "sdk_key_found": application.sdk_key_found,
    }


def main() -> int:
    """Run the redacted APK capability probe."""
    parser = argparse.ArgumentParser(
        description="Extract and inspect an Owlet APK/APKM/XAPK without executing it"
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_report(args.archive, args.destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
