"""Safe extraction of user-supplied Owlet application archives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Final

RUNTIME_PACK_SUFFIX: Final = ".owletcam"
RUNTIME_PACK_FORMAT: Final = "owlet_cam_runtime_pack"
RUNTIME_PACK_SCHEMA_VERSION: Final = 1
RUNTIME_PACK_MANIFEST: Final = "owlet-cam-runtime.json"
RUNTIME_PACK_SDK_KEY: Final = "private/sdk-key"
SUPPORTED_ARCHIVE_SUFFIXES: Final = frozenset(
    {".apk", ".apkm", ".xapk", ".zip", RUNTIME_PACK_SUFFIX}
)
TARGET_ABI: Final = "arm64-v8a"
OWLET_ANDROID_PACKAGES: Final = frozenset(
    {"com.owletcare.sleep", "com.owletcare.owletcare"}
)
REQUIRED_LIBRARIES: Final = frozenset(
    {
        "libAVAPIs.so",
        "libIOTCAPIs.so",
        "libP2PTunnelAPIs.so",
        "libRDTAPIs.so",
        "libTUTKGlobalAPIs.so",
    }
)

# Kalay application licence strings are printable base64-like values. Matching is
# deliberately broad: the actual key is user-supplied material and must never be
# hard-coded into this repository.
_SDK_KEY_RE: Final = re.compile(rb"(?<![A-Za-z0-9+/=_-])AQ[A-Za-z0-9+/=_-]{30,510}")
_PACKAGE_NAME_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+){2,}$")
_VERSION_NAME_RE: Final = re.compile(r"^\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9._-]+)?$")
_SCAN_SUFFIXES: Final = frozenset({".dex", ".so"})
_COPY_CHUNK: Final = 1024 * 1024
_SCAN_OVERLAP: Final = 520


class OwletArchiveError(ValueError):
    """Raised when an application archive fails a safety or content gate."""

    def __init__(self, message: str, *, code: str = "invalid_apk") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Resource limits applied across the outer archive and all nested APKs."""

    maximum_archive_size: int = 512 * 1024 * 1024
    maximum_uncompressed_size: int = 2 * 1024 * 1024 * 1024
    maximum_file_count: int = 50_000
    maximum_nested_archive_size: int = 512 * 1024 * 1024
    maximum_nesting_depth: int = 2


@dataclass(frozen=True, slots=True)
class ExtractedLibrary:
    """Non-secret metadata for one extracted native library."""

    name: str
    path: Path
    sha256: str
    size: int


@dataclass(slots=True, repr=False)
class ExtractedOwletApplication:
    """Result of an allowlisted extraction.

    ``sdk_key`` is intentionally excluded from ``repr``. Callers must pass it to
    the isolated helper over stdin and then discard it; it must not be logged or
    serialized into diagnostics.
    """

    source_sha256: str
    abi: str
    libraries: dict[str, ExtractedLibrary]
    package_name: str | None = None
    app_version: str | None = None
    sdk_key: bytes | None = field(default=None, repr=False)

    @property
    def sdk_key_found(self) -> bool:
        """Return whether exactly one plausible SDK licence key was found."""
        return self.sdk_key is not None


@dataclass(slots=True)
class _Budget:
    limits: ArchiveLimits
    files: int = 0
    uncompressed: int = 0

    def account(self, info: zipfile.ZipInfo) -> None:
        self.files += 1
        self.uncompressed += info.file_size
        if self.files > self.limits.maximum_file_count:
            raise OwletArchiveError("Application archive contains too many files")
        if self.uncompressed > self.limits.maximum_uncompressed_size:
            raise OwletArchiveError(
                "Application archive expands beyond the safety limit"
            )


@dataclass(slots=True)
class _ExtractionState:
    destination: Path
    target_abi: str
    budget: _Budget
    libraries: dict[str, ExtractedLibrary] = field(default_factory=dict)
    sdk_candidates: set[bytes] = field(default_factory=set)
    package_name: str | None = None
    app_version: str | None = None
    runtime_pack_libraries: dict[str, tuple[str, int]] | None = None


def extract_owlet_application(
    archive: Path,
    destination: Path,
    *,
    target_abi: str = TARGET_ABI,
    limits: ArchiveLimits | None = None,
) -> ExtractedOwletApplication:
    """Extract only required libraries and detect the user APK's SDK key.

    The destination may exist but must be empty. Nothing from the archive is
    executed, and nested split APKs are spooled to mode-0600 temporary files
    under the same global file-count and uncompressed-size budget.
    """
    limits = limits or ArchiveLimits()
    _validate_source(archive, limits)
    _prepare_destination(destination)

    source_sha256 = _hash_file(archive)
    state = _ExtractionState(
        destination=destination,
        target_abi=target_abi,
        budget=_Budget(limits),
    )
    try:
        with archive.open("rb") as source:
            _process_zip(source, state, depth=0)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as err:
        raise OwletArchiveError(
            "Application archive is not a valid ZIP archive"
        ) from err

    missing = sorted(REQUIRED_LIBRARIES - state.libraries.keys())
    if missing:
        raise OwletArchiveError(
            "Application archive is missing required ARM64 libraries: "
            + ", ".join(missing),
            code=("missing_arm64_split" if not state.libraries else "missing_library"),
        )
    if len(state.sdk_candidates) > 1:
        raise OwletArchiveError("Application archive contains ambiguous SDK keys")
    if state.runtime_pack_libraries is not None:
        for name, (
            expected_sha256,
            expected_size,
        ) in state.runtime_pack_libraries.items():
            library = state.libraries[name]
            if library.sha256 != expected_sha256 or library.size != expected_size:
                raise OwletArchiveError(
                    "Owlet runtime package library integrity check failed"
                )

    sdk_key = next(iter(state.sdk_candidates), None)
    return ExtractedOwletApplication(
        source_sha256=source_sha256,
        abi=target_abi,
        libraries=dict(sorted(state.libraries.items())),
        package_name=state.package_name,
        app_version=state.app_version,
        sdk_key=sdk_key,
    )


def _validate_source(archive: Path, limits: ArchiveLimits) -> None:
    try:
        source_stat = archive.lstat()
    except OSError as err:
        raise OwletArchiveError("Application archive cannot be read") from err
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise OwletArchiveError("Application archive must be a regular file")
    if archive.suffix.lower() not in SUPPORTED_ARCHIVE_SUFFIXES:
        raise OwletArchiveError("Unsupported application archive type")
    if source_stat.st_size > limits.maximum_archive_size:
        raise OwletArchiveError("Application archive exceeds the size limit")


def _prepare_destination(destination: Path) -> None:
    try:
        destination.mkdir(parents=True, mode=0o700, exist_ok=True)
        if any(destination.iterdir()):
            raise OwletArchiveError("Extraction destination must be empty")
        destination.chmod(0o700)
    except OwletArchiveError:
        raise
    except OSError as err:
        raise OwletArchiveError("Extraction destination cannot be prepared") from err


def _process_zip(source: IO[bytes], state: _ExtractionState, *, depth: int) -> None:
    if depth > state.budget.limits.maximum_nesting_depth:
        raise OwletArchiveError("Application archive nesting exceeds the safety limit")
    with zipfile.ZipFile(source) as archive:
        runtime_pack = _read_runtime_pack_manifest(archive, state, depth=depth)
        for info in archive.infolist():
            _validate_member(info)
            if info.is_dir():
                continue
            state.budget.account(info)
            member = PurePosixPath(info.filename)
            basename = member.name

            if runtime_pack and info.filename == RUNTIME_PACK_MANIFEST:
                continue
            if runtime_pack and info.filename == RUNTIME_PACK_SDK_KEY:
                with archive.open(info, "r") as data:
                    sdk_key = data.read(513)
                if (
                    len(sdk_key) != info.file_size
                    or _SDK_KEY_RE.fullmatch(sdk_key) is None
                ):
                    raise OwletArchiveError(
                        "Owlet runtime package SDK key is invalid",
                        code="missing_sdk_key",
                    )
                state.sdk_candidates.add(sdk_key)
                continue

            if basename == "manifest.json" and info.file_size <= 1024 * 1024:
                with archive.open(info, "r") as data:
                    _read_json_manifest(data, info.file_size, state)
                continue

            if basename == "AndroidManifest.xml" and info.file_size <= 2 * 1024 * 1024:
                with archive.open(info, "r") as data:
                    _read_android_manifest(data, info.file_size, state)
                continue

            if _is_target_library(member, basename, state.target_abi):
                with archive.open(info, "r") as data:
                    _extract_library(data, basename, info.file_size, state)
                continue

            if member.suffix.lower() == ".apk":
                if info.file_size > state.budget.limits.maximum_nested_archive_size:
                    raise OwletArchiveError("Nested APK exceeds the size limit")
                with tempfile.TemporaryFile(
                    mode="w+b", dir=state.destination
                ) as nested:
                    os.fchmod(nested.fileno(), 0o600)
                    with archive.open(info, "r") as data:
                        _copy_limited(
                            data,
                            nested,
                            state.budget.limits.maximum_nested_archive_size,
                        )
                    nested.seek(0)
                    _process_zip(nested, state, depth=depth + 1)
                continue

            if member.suffix.lower() in _SCAN_SUFFIXES:
                with archive.open(info, "r") as data:
                    _scan_sdk_key(data, state.sdk_candidates)


def _read_runtime_pack_manifest(
    archive: zipfile.ZipFile, state: _ExtractionState, *, depth: int
) -> bool:
    """Recognize and strictly validate one compact desktop-prepared package."""
    matching = [
        info for info in archive.infolist() if info.filename == RUNTIME_PACK_MANIFEST
    ]
    if not matching:
        return False
    if depth != 0 or len(matching) != 1:
        raise OwletArchiveError("Owlet runtime package structure is invalid")
    info = matching[0]
    _validate_member(info)
    if info.file_size > 64 * 1024:
        raise OwletArchiveError("Owlet runtime package manifest is too large")
    try:
        with archive.open(info, "r") as source:
            document: object = json.loads(source.read(64 * 1024 + 1))
    except (KeyError, UnicodeError, json.JSONDecodeError) as err:
        raise OwletArchiveError("Owlet runtime package manifest is invalid") from err
    if not isinstance(document, dict):
        raise OwletArchiveError("Owlet runtime package manifest is invalid")
    if set(document) != {
        "format",
        "schema_version",
        "application_source_sha256",
        "package_name",
        "app_version",
        "abi",
        "libraries",
    }:
        raise OwletArchiveError("Owlet runtime package manifest is invalid")
    if (
        document.get("format") != RUNTIME_PACK_FORMAT
        or document.get("schema_version") != RUNTIME_PACK_SCHEMA_VERSION
        or document.get("abi") != TARGET_ABI
        or document.get("package_name") not in OWLET_ANDROID_PACKAGES
    ):
        raise OwletArchiveError("Owlet runtime package is incompatible")
    version = document.get("app_version")
    source_sha256 = document.get("application_source_sha256")
    libraries = document.get("libraries")
    if (
        (version is not None and (not isinstance(version, str) or len(version) > 64))
        or not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256)
        or not isinstance(libraries, list)
    ):
        raise OwletArchiveError("Owlet runtime package manifest is invalid")

    expected_libraries: dict[str, tuple[str, int]] = {}
    expected_paths = {RUNTIME_PACK_MANIFEST, RUNTIME_PACK_SDK_KEY}
    for item in libraries:
        if not isinstance(item, dict):
            raise OwletArchiveError("Owlet runtime package manifest is invalid")
        if set(item) != {"name", "path", "sha256", "size"}:
            raise OwletArchiveError("Owlet runtime package manifest is invalid")
        name = item.get("name")
        path = item.get("path")
        sha256 = item.get("sha256")
        size = item.get("size")
        if (
            name not in REQUIRED_LIBRARIES
            or path != f"lib/{TARGET_ABI}/{name}"
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or name in expected_libraries
        ):
            raise OwletArchiveError("Owlet runtime package manifest is invalid")
        expected_libraries[name] = (sha256, size)
        expected_paths.add(path)
    if set(expected_libraries) != REQUIRED_LIBRARIES:
        raise OwletArchiveError("Owlet runtime package is incomplete")

    members = archive.infolist()
    member_names = [info.filename for info in members]
    if (
        any(info.is_dir() for info in members)
        or len(member_names) != len(set(member_names))
        or set(member_names) != expected_paths
    ):
        raise OwletArchiveError("Owlet runtime package contains unexpected files")
    by_name = {info.filename: info for info in archive.infolist()}
    for path in expected_paths:
        _validate_member(by_name[path])
    if by_name[RUNTIME_PACK_SDK_KEY].file_size > 512:
        raise OwletArchiveError(
            "Owlet runtime package SDK key is invalid", code="missing_sdk_key"
        )
    for name, (_sha256, size) in expected_libraries.items():
        if by_name[f"lib/{TARGET_ABI}/{name}"].file_size != size:
            raise OwletArchiveError(
                "Owlet runtime package library integrity check failed"
            )
    state.package_name = document["package_name"]
    state.app_version = version
    state.runtime_pack_libraries = expected_libraries
    return True


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if "\\" in name or "\x00" in name:
        raise OwletArchiveError("Application archive contains an unsafe path")
    member = PurePosixPath(name)
    if member.is_absolute() or any(part in {"", ".", ".."} for part in member.parts):
        raise OwletArchiveError("Application archive contains path traversal")
    if member.parts and ":" in member.parts[0]:
        raise OwletArchiveError("Application archive contains an absolute path")

    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise OwletArchiveError("Application archive contains a link or special file")


def _is_target_library(member: PurePosixPath, basename: str, target_abi: str) -> bool:
    if basename not in REQUIRED_LIBRARIES:
        return False
    parts = tuple(part.lower().replace("_", "-") for part in member.parts)
    return target_abi.lower() in parts


def _extract_library(
    source: IO[bytes],
    name: str,
    expected_size: int,
    state: _ExtractionState,
) -> None:
    library_dir = state.destination / state.target_abi
    library_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    output = library_dir / name
    temporary = library_dir / f".{name}.partial"
    digest = hashlib.sha256()
    written = 0
    scan_overlap = b""
    try:
        with temporary.open("xb") as target:
            os.chmod(target.fileno(), 0o500)
            while chunk := source.read(_COPY_CHUNK):
                written += len(chunk)
                if written > expected_size:
                    raise OwletArchiveError("Library entry exceeded its declared size")
                digest.update(chunk)
                scan_data = scan_overlap + chunk
                state.sdk_candidates.update(
                    match.group(0) for match in _SDK_KEY_RE.finditer(scan_data)
                )
                scan_overlap = scan_data[-_SCAN_OVERLAP:]
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if written != expected_size:
            raise OwletArchiveError("Library entry ended before its declared size")
        sha256 = digest.hexdigest()
        previous = state.libraries.get(name)
        if previous is not None:
            if previous.sha256 != sha256:
                raise OwletArchiveError(
                    "Application archive contains conflicting libraries"
                )
            temporary.unlink(missing_ok=True)
            return
        os.replace(temporary, output)
        output.chmod(0o500)
        state.libraries[name] = ExtractedLibrary(
            name=name,
            path=output,
            sha256=sha256,
            size=written,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _scan_sdk_key(source: IO[bytes], candidates: set[bytes]) -> None:
    overlap = b""
    while chunk := source.read(_COPY_CHUNK):
        data = overlap + chunk
        candidates.update(match.group(0) for match in _SDK_KEY_RE.finditer(data))
        overlap = data[-_SCAN_OVERLAP:]


def _copy_limited(source: IO[bytes], target: IO[bytes], maximum: int) -> None:
    written = 0
    while chunk := source.read(_COPY_CHUNK):
        written += len(chunk)
        if written > maximum:
            raise OwletArchiveError("Nested APK exceeds the size limit")
        target.write(chunk)


def _read_json_manifest(
    source: IO[bytes], expected_size: int, state: _ExtractionState
) -> None:
    try:
        payload = _read_exact_limited(source, expected_size, 1024 * 1024)
        document = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return
    if not isinstance(document, dict):
        return
    version = document.get("version_name", document.get("versionName"))
    package = document.get("package_name", document.get("package"))
    if state.app_version is None and isinstance(version, str) and len(version) <= 64:
        state.app_version = version
    if state.package_name is None and isinstance(package, str) and len(package) <= 255:
        state.package_name = package


def _read_android_manifest(
    source: IO[bytes], expected_size: int, state: _ExtractionState
) -> None:
    """Read only package/version strings from Android's binary XML format."""
    try:
        payload = _read_exact_limited(source, expected_size, 2 * 1024 * 1024)
        package, version = _parse_binary_android_manifest(payload)
    except (OSError, UnicodeError, ValueError, struct.error):
        return
    if state.package_name is None:
        state.package_name = package
    if state.app_version is None:
        state.app_version = version


def _read_exact_limited(source: IO[bytes], expected: int, maximum: int) -> bytes:
    if expected < 0 or expected > maximum:
        raise ValueError("Manifest size is outside its limit")
    payload = source.read(maximum + 1)
    if len(payload) != expected or len(payload) > maximum:
        raise ValueError("Manifest entry size is inconsistent")
    return payload


def _parse_binary_android_manifest(payload: bytes) -> tuple[str | None, str | None]:
    if len(payload) < 8:
        raise ValueError("Android manifest is truncated")
    xml_type, header_size, total_size = struct.unpack_from("<HHI", payload)
    if xml_type != 0x0003 or header_size < 8 or total_size > len(payload):
        raise ValueError("Android manifest header is invalid")
    strings: list[str] = []
    offset = header_size
    while offset + 8 <= total_size:
        chunk_type, chunk_header, chunk_size = struct.unpack_from(
            "<HHI", payload, offset
        )
        if (
            chunk_size < chunk_header
            or chunk_size < 8
            or offset + chunk_size > total_size
        ):
            raise ValueError("Android manifest chunk is invalid")
        if chunk_type == 0x0001:
            strings.extend(
                _parse_string_pool(payload, offset, chunk_header, chunk_size)
            )
        offset += chunk_size
    packages = [value for value in strings if _PACKAGE_NAME_RE.fullmatch(value)]
    versions = [value for value in strings if _VERSION_NAME_RE.fullmatch(value)]
    package = next(
        (value for value in packages if "owlet" in value.lower()),
        packages[0] if packages else None,
    )
    return package, versions[0] if versions else None


def _parse_string_pool(
    payload: bytes, offset: int, header_size: int, chunk_size: int
) -> list[str]:
    if header_size < 28:
        raise ValueError("Android string pool header is invalid")
    string_count, _style_count, flags, strings_start = struct.unpack_from(
        "<IIII", payload, offset + 8
    )
    if string_count > 100_000 or 28 + string_count * 4 > header_size:
        raise ValueError("Android string pool count is invalid")
    utf8 = bool(flags & 0x100)
    result: list[str] = []
    pool_end = offset + chunk_size
    for index in range(string_count):
        relative = struct.unpack_from("<I", payload, offset + 28 + index * 4)[0]
        position = offset + strings_start + relative
        if not offset <= position < pool_end:
            raise ValueError("Android string offset is invalid")
        result.append(_decode_pool_string(payload, position, pool_end, utf8))
    return result


def _decode_pool_string(payload: bytes, position: int, end: int, utf8: bool) -> str:
    if utf8:
        _, position = _decode_length8(payload, position, end)
        length, position = _decode_length8(payload, position, end)
        if position + length >= end:
            raise ValueError("Android UTF-8 string is truncated")
        return payload[position : position + length].decode("utf-8")
    length, position = _decode_length16(payload, position, end)
    byte_length = length * 2
    if position + byte_length + 2 > end:
        raise ValueError("Android UTF-16 string is truncated")
    return payload[position : position + byte_length].decode("utf-16-le")


def _decode_length8(payload: bytes, position: int, end: int) -> tuple[int, int]:
    if position >= end:
        raise ValueError("Android string length is truncated")
    first = payload[position]
    if first & 0x80:
        if position + 1 >= end:
            raise ValueError("Android string length is truncated")
        return ((first & 0x7F) << 8) | payload[position + 1], position + 2
    return first, position + 1


def _decode_length16(payload: bytes, position: int, end: int) -> tuple[int, int]:
    if position + 2 > end:
        raise ValueError("Android string length is truncated")
    first = struct.unpack_from("<H", payload, position)[0]
    if first & 0x8000:
        if position + 4 > end:
            raise ValueError("Android string length is truncated")
        second = struct.unpack_from("<H", payload, position + 2)[0]
        return ((first & 0x7FFF) << 16) | second, position + 4
    return first, position + 2


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
