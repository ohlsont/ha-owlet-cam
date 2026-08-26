"""Actionable repair issues for the isolated Owlet runtime."""

from __future__ import annotations

from typing import Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, EXPECTED_HELPER_VERSION
from .runtime.manager import OwletRuntimeManager

_REPAIR_CODES: Final = frozenset(
    {
        "missing_apk",
        "missing_arm64_split",
        "missing_library",
        "missing_sdk_key",
        "unsupported_architecture",
        "library_incompatible",
        "invalid_apk",
        "invalid_extracted_files",
        "invalid_runtime_manifest",
        "invalid_runtime_storage",
        "runtime_checksum_mismatch",
        "runtime_download_failed",
        "missing_runtime",
        "obsolete_helper_runtime",
        "runtime_state_write_failed",
        "reauthentication_required",
        "stream_recovery_failed",
    }
)


@callback
def async_sync_runtime_issues(
    hass: HomeAssistant,
    entry_id: str,
    manager: OwletRuntimeManager,
) -> None:
    """Create the current safe issue and remove every resolved issue."""
    active = manager.snapshot.last_error_code
    if not manager.supported_architecture:
        active = "unsupported_architecture"
    elif (
        manager.snapshot.helper_version is not None
        and manager.snapshot.helper_version != EXPECTED_HELPER_VERSION
        and not manager.snapshot.helper_version.endswith("-test")
    ):
        active = "obsolete_helper_runtime"
    if active not in _REPAIR_CODES:
        active = None

    for code in _REPAIR_CODES:
        issue_id = f"{entry_id}_{code}"
        if code != active:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            continue
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=True,
            severity=(
                ir.IssueSeverity.ERROR
                if code in {"unsupported_architecture", "library_incompatible"}
                else ir.IssueSeverity.WARNING
            ),
            translation_key=code,
        )


@callback
def async_remove_runtime_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove all issues owned by an unloaded or removed config entry."""
    for code in _REPAIR_CODES:
        ir.async_delete_issue(hass, DOMAIN, f"{entry_id}_{code}")
