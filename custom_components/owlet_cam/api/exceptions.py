"""Typed Owlet Cam API exceptions."""


class OwletCamError(Exception):
    """Base exception for safe, redacted Owlet Cam failures."""


class OwletAuthenticationError(OwletCamError):
    """The Owlet account credentials or token are no longer valid."""


class OwletConnectionError(OwletCamError):
    """The Owlet service could not be reached or returned invalid data."""


class OwletCameraNotFoundError(OwletCamError):
    """The requested camera is not available to the authenticated account."""


class OwletRateLimitError(OwletCamError):
    """The Owlet service rejected the request due to rate limiting."""


class OwletUnsupportedRegionError(OwletCamError):
    """The requested Owlet cloud region is unsupported."""


class OwletInvalidDSNError(OwletCamError):
    """The camera DSN is malformed."""

    def __init__(self, *, confused_zero: bool = False) -> None:
        """Create a safe DSN validation error."""
        super().__init__("The camera DSN format is invalid")
        self.confused_zero = confused_zero
