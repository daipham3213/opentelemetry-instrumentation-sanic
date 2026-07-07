"""Unit tests for the small metadata modules ``package`` and ``version``."""

from __future__ import annotations

from opentelemetry.instrumentation.sanic.package import _instruments
from opentelemetry.instrumentation.sanic.version import __version__


def test_instruments_targets_sanic() -> None:
    assert any("sanic" in specifier for specifier in _instruments)


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__
