"""Expected failures. The CLI prints their message and exits non-zero instead of a traceback.

Messages must never contain the token.
"""


class FlxError(Exception):
    """Base class for every failure flx raises on purpose."""


class TokenError(FlxError):
    """No usable token (missing or malformed); raised before any request is sent."""


class ReadOnlyError(FlxError):
    """Something tried to send a request other than GET."""


class InvalidInputError(FlxError):
    """User input rejected before any request is sent."""


class AuthError(FlxError):
    """HTTP 401: the token is invalid or expired."""


class NotFoundError(FlxError):
    """HTTP 404."""


class RateLimitError(FlxError):
    """HTTP 429 persisted after every retry."""


class NetworkError(FlxError):
    """Connection failed or timed out."""


class BadResponseError(FlxError):
    """The response body was not the JSON envelope we expect."""


class ApiError(FlxError):
    """Any other error status or error envelope from Freelancer."""
