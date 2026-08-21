"""Native runtime structural gate tests."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from custom_components.owlet_cam.runtime.elf import (
    EM_AARCH64,
    EM_X86_64,
    ElfInspectionError,
    inspect_elf,
)


def _minimal_elf(
    *,
    machine: int = EM_AARCH64,
    writable_executable: bool = False,
    include_nobits: bool = False,
    symbol_defined: bool = True,
) -> bytes:
    program_offset = 64
    section_offset = 128
    section_count = 5 if include_nobits else 4
    string_offset = section_offset + section_count * 64
    strings = b"\0libc.so\0probe_symbol\0"
    symbol_offset = string_offset + len(strings)
    dynamic_offset = symbol_offset + 48
    total_size = dynamic_offset + 32
    data = bytearray(total_size)

    identifier = bytearray(16)
    identifier[:4] = b"\x7fELF"
    identifier[4] = 2
    identifier[5] = 1
    identifier[6] = 1
    struct.pack_into(
        "<16sHHIQQQIHHHHHH",
        data,
        0,
        bytes(identifier),
        3,
        machine,
        1,
        0,
        program_offset,
        section_offset,
        0,
        64,
        56,
        1,
        64,
        section_count,
        0,
    )
    flags = 7 if writable_executable else 5
    struct.pack_into(
        "<IIQQQQQQ",
        data,
        program_offset,
        1,
        flags,
        0,
        0,
        0,
        total_size,
        total_size,
        4096,
    )

    def section(
        index: int,
        section_type: int,
        offset: int,
        size: int,
        *,
        link: int = 0,
        entry_size: int = 0,
    ) -> None:
        struct.pack_into(
            "<IIQQQQIIQQ",
            data,
            section_offset + index * 64,
            0,
            section_type,
            0,
            0,
            offset,
            size,
            link,
            0,
            1,
            entry_size,
        )

    section(0, 0, 0, 0)
    section(1, 3, string_offset, len(strings))
    section(2, 11, symbol_offset, 48, link=1, entry_size=24)
    section(3, 6, dynamic_offset, 32, link=1, entry_size=16)
    if include_nobits:
        section(4, 8, total_size + 4096, 4096)
    data[string_offset : string_offset + len(strings)] = strings
    struct.pack_into(
        "<IBBHQQ", data, symbol_offset + 24, 9, 0, 0, int(symbol_defined), 0, 0
    )
    struct.pack_into("<QQ", data, dynamic_offset, 1, 1)
    struct.pack_into("<QQ", data, dynamic_offset + 16, 0, 0)
    return bytes(data)


def test_inspects_arm64_dependencies_and_symbols(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf())

    report = inspect_elf(library, required_symbols=frozenset({"probe_symbol"}))

    assert report.architecture == "AArch64"
    assert report.dependencies == ("libc.so",)
    assert report.required_symbols_present is True
    assert report.has_writable_executable_segment is False


def test_reports_missing_required_symbol(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf())

    report = inspect_elf(library, required_symbols=frozenset({"missing"}))

    assert report.required_symbols_present is False
    assert report.missing_required_symbols == ("missing",)


def test_does_not_count_undefined_import_as_export(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(symbol_defined=False))

    report = inspect_elf(library, required_symbols=frozenset({"probe_symbol"}))

    assert report.required_symbols_present is False


def test_rejects_wrong_architecture(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(machine=EM_X86_64))

    with pytest.raises(ElfInspectionError, match="expected AArch64"):
        inspect_elf(library)


def test_detects_writable_executable_segment(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(writable_executable=True))

    report = inspect_elf(library)

    assert report.has_writable_executable_segment is True


def test_accepts_nobits_section_without_file_backing(tmp_path: Path) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(_minimal_elf(include_nobits=True))

    report = inspect_elf(library)

    assert report.architecture == "AArch64"


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"not-elf", "not an ELF"), (b"\x7fELF" + b"\0" * 80, "not 64-bit")],
)
def test_rejects_malformed_elf(tmp_path: Path, content: bytes, message: str) -> None:
    library = tmp_path / "library.so"
    library.write_bytes(content)

    with pytest.raises(ElfInspectionError, match=message):
        inspect_elf(library)
