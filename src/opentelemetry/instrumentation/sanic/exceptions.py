"""Custom exception hierarchy for the Sanic instrumentation package.

A dedicated hierarchy lets callers catch instrumentation-specific failures
without swallowing unrelated errors, and keeps every ``except`` clause in the
package narrow and intentional.

The hierarchy is::

    SanicInstrumentationError                 (base)
    ├── SanicConfigurationError               invalid configuration
    ├── MiddlewareRegistrationError           middleware could not be attached
    └── RequestAttributeError                 object is not a Sanic request
"""

from __future__ import annotations

__all__ = [
    "MiddlewareRegistrationError",
    "RequestAttributeError",
    "SanicConfigurationError",
    "SanicInstrumentationError",
]


class SanicInstrumentationError(Exception):
    """Base class for every error raised by this package.

    Catch this to handle *any* failure originating from the Sanic
    instrumentation while leaving unrelated exceptions to propagate.
    """


class SanicConfigurationError(SanicInstrumentationError):
    """Raised when the instrumentation is given invalid configuration.

    For example, an ``excluded_urls`` value that is not valid
    regular-expression syntax. Distinct from :class:`RequestAttributeError`,
    which concerns runtime request objects rather than static configuration.
    """


class MiddlewareRegistrationError(SanicInstrumentationError):
    """Raised when OpenTelemetry middleware cannot be attached to an app.

    This typically indicates an incompatible Sanic version whose
    ``register_middleware`` signature differs from what is expected.
    """


class RequestAttributeError(SanicInstrumentationError):
    """Raised when telemetry cannot be derived from a request object.

    Signals that the incoming object does not expose the Sanic request
    interface this package relies on (in practice, that it has no ``method``).
    """
