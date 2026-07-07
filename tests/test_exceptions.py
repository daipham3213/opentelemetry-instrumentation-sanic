"""Unit tests for the package exception hierarchy."""

from __future__ import annotations

import pytest

from opentelemetry.instrumentation.sanic.exceptions import (
    MiddlewareRegistrationError,
    RequestAttributeError,
    SanicConfigurationError,
    SanicInstrumentationError,
)


@pytest.mark.parametrize(
    "subclass",
    [
        SanicConfigurationError,
        MiddlewareRegistrationError,
        RequestAttributeError,
    ],
)
def test_all_errors_derive_from_the_base(subclass) -> None:
    assert issubclass(subclass, SanicInstrumentationError)


@pytest.mark.parametrize(
    "subclass",
    [
        SanicConfigurationError,
        MiddlewareRegistrationError,
        RequestAttributeError,
    ],
)
def test_subclasses_are_catchable_as_base(subclass) -> None:
    with pytest.raises(SanicInstrumentationError):
        raise subclass("boom")


def test_configuration_and_request_errors_are_siblings() -> None:
    # A config error must not be caught as a request-attribute error, and
    # vice versa; they are distinct branches of the hierarchy.
    assert not issubclass(SanicConfigurationError, RequestAttributeError)
    assert not issubclass(RequestAttributeError, SanicConfigurationError)
