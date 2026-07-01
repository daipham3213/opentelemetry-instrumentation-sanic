"""Custom exception hierarchy for the Sanic instrumentation package.

Defining a dedicated hierarchy lets callers catch instrumentation-specific
failures without swallowing unrelated errors, and keeps the ``except`` clauses
throughout the package narrow and intentional.
"""

from __future__ import annotations


class SanicInstrumentationError(Exception):
    """Base class for every error raised by this package.

    Catch this to handle *any* failure originating from the Sanic
    instrumentation while leaving unrelated exceptions to propagate.
    """


class MiddlewareRegistrationError(SanicInstrumentationError):
    """Raised when OpenTelemetry middleware cannot be attached to an app.

    This typically indicates an incompatible Sanic version whose
    ``register_middleware`` signature differs from what is expected.
    """


class RequestAttributeError(SanicInstrumentationError):
    """Raised when span attributes cannot be derived from a request object.

    Signals that the incoming object does not expose the Sanic request
    interface this package relies on.
    """


__all__ = [
    "MiddlewareRegistrationError",
    "RequestAttributeError",
    "SanicInstrumentationError",
]
