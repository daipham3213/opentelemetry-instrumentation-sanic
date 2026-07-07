"""Unit tests for :class:`._instrumentor.SanicInstrumentor`.

These verify the activation contract — patching and restoring
``sanic.Sanic.__init__`` — without exercising a full request (that is
``test_integration``'s job). ``sanic.Sanic.__init__`` is snapshotted and
restored around every test so the module-level patch can never leak between
tests, regardless of assertion failures.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sanic

from opentelemetry.instrumentation.sanic import SanicInstrumentor
from opentelemetry.instrumentation.sanic._instrumentor import _OTEL_PATCH_FLAG
from opentelemetry.instrumentation.sanic.package import _instruments


@pytest.fixture
def instrumentor() -> Iterator[SanicInstrumentor]:
    """Yield an instrumentor and guarantee the ``Sanic.__init__`` patch is
    reverted afterwards."""
    original_init = sanic.Sanic.__init__
    instance = SanicInstrumentor()
    try:
        yield instance
    finally:
        instance.uninstrument()
        # Defensive: restore by hand in case a test left it patched.
        sanic.Sanic.__init__ = original_init


def test_instrument_patches_sanic_init(
    instrumentor: SanicInstrumentor,
) -> None:
    assert not getattr(sanic.Sanic.__init__, _OTEL_PATCH_FLAG, False)

    instrumentor.instrument()

    assert getattr(sanic.Sanic.__init__, _OTEL_PATCH_FLAG, False) is True


def test_uninstrument_restores_original_init(
    instrumentor: SanicInstrumentor,
) -> None:
    original_init = sanic.Sanic.__init__

    instrumentor.instrument()
    assert sanic.Sanic.__init__ is not original_init

    instrumentor.uninstrument()
    assert sanic.Sanic.__init__ is original_init
    assert not getattr(sanic.Sanic.__init__, _OTEL_PATCH_FLAG, False)


def test_instrument_is_idempotent(instrumentor: SanicInstrumentor) -> None:
    instrumentor.instrument()
    patched_init = sanic.Sanic.__init__

    # A second activation must not re-wrap the already-patched constructor.
    instrumentor.instrument()

    assert sanic.Sanic.__init__ is patched_init


def test_instrumentation_dependencies(
    instrumentor: SanicInstrumentor,
) -> None:
    assert instrumentor.instrumentation_dependencies() == _instruments


def test_uninstrument_before_instrument_is_safe(
    instrumentor: SanicInstrumentor,
) -> None:
    original_init = sanic.Sanic.__init__

    instrumentor.uninstrument()  # never instrumented -> no-op

    assert sanic.Sanic.__init__ is original_init
