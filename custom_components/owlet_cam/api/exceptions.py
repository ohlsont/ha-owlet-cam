"""Typed Owlet Cam API exceptions."""


class OwletCamError(Exception):
    """Base exception for safe, redacted Owlet Cam failures."""


class OwletAuthenticationError(OwletCamError):
    """The Owlet account credentials or token are no longer valid."""

    def __init__(
        self,
        message: str = "Owlet account authentication failed",
        *,
        reason: str = "authentication_failed",
    ) -> None:
        """Create an authentication failure with a coarse safe reason."""
        super().__init__(message)
        self.reason = reason


class OwletConnectionError(OwletCamError):
    """The Owlet service could not be reached or returned invalid data."""

    def __init__(
        self,
        message: str = "Owlet service connection failed",
        *,
        reason: str = "connection_failed",
        http_status: int | None = None,
    ) -> None:
        """Create a connection failure with safe transport metadata."""
        super().__init__(message)
        self.reason = reason
        self.http_status = http_status


class OwletCameraNotFoundError(OwletCamError):
    """The requested camera is not available to the authenticated account."""

    def __init__(
        self,
        message: str = "Camera is not available to this Owlet account",
        *,
        reason: str = "camera_unavailable",
        http_status: int | None = None,
    ) -> None:
        """Create a camera lookup failure with safe HTTP status metadata."""
        super().__init__(message)
        self.reason = reason
        self.http_status = http_status


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
