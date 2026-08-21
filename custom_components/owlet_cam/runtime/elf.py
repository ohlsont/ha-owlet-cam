"""Small, dependency-free ELF64 inspector for the native runtime gate."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_ELF_MAGIC: Final = b"\x7fELF"
_ELFCLASS64: Final = 2
_ELFDATA2LSB: Final = 1
EM_AARCH64: Final = 183
EM_X86_64: Final = 62
_PT_LOAD: Final = 1
_PT_INTERP: Final = 3
_PF_X: Final = 1
_PF_W: Final = 2
_SHT_DYNAMIC: Final = 6
_SHT_DYNSYM: Final = 11
_DT_NULL: Final = 0
_DT_NEEDED: Final = 1


class ElfInspectionError(ValueError):
    """Raised when a native library is malformed or outside the supported ABI."""


@dataclass(frozen=True, slots=True)
class ElfReport:
    """Non-secret structural facts about one ELF shared object."""

    architecture: str
    elf_class: int
    little_endian: bool
    interpreter: str | None
    dependencies: tuple[str, ...]
    exported_symbols: frozenset[str]
    missing_required_symbols: tuple[str, ...]
    has_writable_executable_segment: bool

    @property
    def required_symbols_present(self) -> bool:
        """Return whether every requested dynamic symbol was found."""
        return not self.missing_required_symbols


@dataclass(frozen=True, slots=True)
class _Section:
    section_type: int
    offset: int
    size: int
    link: int
    entry_size: int


def inspect_elf(
    path: Path,
    *,
    required_symbols: frozenset[str] = frozenset(),
    expected_machine: int = EM_AARCH64,
) -> ElfReport:
    """Inspect an ELF64 little-endian shared object without loading it."""
    try:
        data = path.read_bytes()
    except OSError as err:
        raise ElfInspectionError("Native library cannot be read") from err
    if len(data) < 64 or data[:4] != _ELF_MAGIC:
        raise ElfInspectionError("Native library is not an ELF file")
    if data[4] != _ELFCLASS64:
        raise ElfInspectionError("Native library is not 64-bit ELF")
    if data[5] != _ELFDATA2LSB:
        raise ElfInspectionError("Native library is not little-endian ELF")

    machine = _unpack_from("<H", data, 18)[0]
    architecture = {EM_AARCH64: "AArch64", EM_X86_64: "x86-64"}.get(
        machine, f"machine-{machine}"
    )
    if machine != expected_machine:
        expected = {EM_AARCH64: "AArch64", EM_X86_64: "x86-64"}.get(
            expected_machine, str(expected_machine)
        )
        raise ElfInspectionError(
            f"Native library architecture is {architecture}, expected {expected}"
        )

    program_offset = _unpack_from("<Q", data, 32)[0]
    section_offset = _unpack_from("<Q", data, 40)[0]
    program_entry_size = _unpack_from("<H", data, 54)[0]
    program_count = _unpack_from("<H", data, 56)[0]
    section_entry_size = _unpack_from("<H", data, 58)[0]
    section_count = _unpack_from("<H", data, 60)[0]

    interpreter, writable_executable = _inspect_program_headers(
        data,
        offset=program_offset,
        entry_size=program_entry_size,
        count=program_count,
    )
    sections = _read_sections(
        data,
        offset=section_offset,
        entry_size=section_entry_size,
        count=section_count,
    )
    dependencies = _read_dependencies(data, sections)
    symbols = _read_dynamic_symbols(data, sections)
    missing = tuple(sorted(required_symbols - symbols))
    return ElfReport(
        architecture=architecture,
        elf_class=64,
        little_endian=True,
        interpreter=interpreter,
        dependencies=tuple(sorted(dependencies)),
        exported_symbols=frozenset(symbols),
        missing_required_symbols=missing,
        has_writable_executable_segment=writable_executable,
    )


def _inspect_program_headers(
    data: bytes, *, offset: int, entry_size: int, count: int
) -> tuple[str | None, bool]:
    if count and entry_size < 56:
        raise ElfInspectionError("ELF program header table is malformed")
    interpreter: str | None = None
    writable_executable = False
    for index in range(count):
        start = offset + index * entry_size
        values = _unpack_from("<IIQQQQQQ", data, start)
        segment_type, flags, file_offset, _, _, file_size, _, _ = values
        _require_range(data, file_offset, file_size)
        if segment_type == _PT_INTERP:
            interpreter = _decode_c_string(data[file_offset : file_offset + file_size])
        if segment_type == _PT_LOAD and flags & _PF_W and flags & _PF_X:
            writable_executable = True
    return interpreter, writable_executable


def _read_sections(
    data: bytes, *, offset: int, entry_size: int, count: int
) -> tuple[_Section, ...]:
    if count and entry_size < 64:
        raise ElfInspectionError("ELF section header table is malformed")
    sections: list[_Section] = []
    for index in range(count):
        start = offset + index * entry_size
        values = _unpack_from("<IIQQQQIIQQ", data, start)
        _, section_type, _, _, file_offset, size, link, _, _, entry = values
        _require_range(data, file_offset, size)
        sections.append(
            _Section(
                section_type=section_type,
                offset=file_offset,
                size=size,
                link=link,
                entry_size=entry,
            )
        )
    return tuple(sections)


def _read_dependencies(data: bytes, sections: tuple[_Section, ...]) -> set[str]:
    dependencies: set[str] = set()
    for section in sections:
        if section.section_type != _SHT_DYNAMIC:
            continue
        strings = _linked_string_table(data, sections, section)
        entry_size = section.entry_size or 16
        if entry_size < 16 or section.size % entry_size:
            raise ElfInspectionError("ELF dynamic section is malformed")
        for relative in range(0, section.size, entry_size):
            tag, value = _unpack_from("<QQ", data, section.offset + relative)
            if tag == _DT_NULL:
                break
            if tag == _DT_NEEDED:
                dependencies.add(_string_at(strings, value))
    return dependencies


def _read_dynamic_symbols(data: bytes, sections: tuple[_Section, ...]) -> set[str]:
    symbols: set[str] = set()
    for section in sections:
        if section.section_type != _SHT_DYNSYM:
            continue
        strings = _linked_string_table(data, sections, section)
        entry_size = section.entry_size or 24
        if entry_size < 24 or section.size % entry_size:
            raise ElfInspectionError("ELF dynamic symbol table is malformed")
        for relative in range(0, section.size, entry_size):
            name_offset = _unpack_from("<I", data, section.offset + relative)[0]
            if name_offset:
                symbols.add(_string_at(strings, name_offset))
    return symbols


def _linked_string_table(
    data: bytes, sections: tuple[_Section, ...], section: _Section
) -> bytes:
    if section.link >= len(sections):
        raise ElfInspectionError("ELF section links to a missing string table")
    strings = sections[section.link]
    return data[strings.offset : strings.offset + strings.size]


def _string_at(strings: bytes, offset: int) -> str:
    if offset >= len(strings):
        raise ElfInspectionError("ELF string table offset is out of bounds")
    return _decode_c_string(strings[offset:])


def _decode_c_string(value: bytes) -> str:
    raw = value.split(b"\0", maxsplit=1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ElfInspectionError("ELF contains an invalid UTF-8 string") from err


def _unpack_from(format_string: str, data: bytes, offset: int) -> tuple[int, ...]:
    size = struct.calcsize(format_string)
    _require_range(data, offset, size)
    return struct.unpack_from(format_string, data, offset)


def _require_range(data: bytes, offset: int, size: int) -> None:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ElfInspectionError("ELF table points outside the file")
