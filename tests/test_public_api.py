"""Tests guarding the public API surface re-exported from ``__init__``."""

from __future__ import annotations

import opentelemetry.instrumentation.sanic as pkg

EXPECTED_PUBLIC_NAMES = {
    "MiddlewareRegistrationError",
    "RequestAttributeError",
    "SanicConfigurationError",
    "SanicInstrumentationError",
    "SanicInstrumentor",
    "__version__",
}


def test_all_declares_the_expected_public_names() -> None:
    assert set(pkg.__all__) == EXPECTED_PUBLIC_NAMES


def test_every_exported_name_is_importable() -> None:
    for name in pkg.__all__:
        assert hasattr(pkg, name), f"{name} is declared in __all__ but missing"
