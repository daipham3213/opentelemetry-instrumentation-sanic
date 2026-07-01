"""Declares the third-party libraries this instrumentation targets.

The :data:`_instruments` tuple is consumed by
:class:`opentelemetry.instrumentation.instrumentor.BaseInstrumentor` (via
:meth:`SanicInstrumentor.instrumentation_dependencies`) to verify that a
*compatible* version of Sanic is importable before any patching happens.
"""

from __future__ import annotations

from collections.abc import Collection

#: Version specifiers (:pep:`508`) for the libraries this package instruments.
_instruments: Collection[str] = ("sanic >= 20.12.0",)

__all__ = ["_instruments"]
