"""Zero-code OpenTelemetry instrumentation for the Sanic web framework.

This package exposes :class:`SanicInstrumentor`, a
:class:`~opentelemetry.instrumentation.instrumentor.BaseInstrumentor` that
transparently instruments every inbound request handled by Sanic — including
apps served over ASGI — emitting both a server span and the standard HTTP
server metrics.

It is wired to the ``opentelemetry_instrumentor`` entry-point group, so once
installed it is discovered and activated automatically by the
``opentelemetry-instrument`` launcher with **no code changes**:

.. code-block:: console

    opentelemetry-instrument python my_sanic_app.py

Equivalently, it can be enabled programmatically:

.. code-block:: python

    from opentelemetry.instrumentation.sanic import SanicInstrumentor

    SanicInstrumentor().instrument()  # do this *before* creating your app
    app = Sanic("my-app")

Architecture
------------
Responsibilities are split across small, single-purpose modules:

* ``exceptions`` — the package's custom exception hierarchy;
* ``_request`` — an anti-corruption layer isolating all access to Sanic's
  duck-typed request/response objects;
* ``_span_attributes`` / ``_metric_attributes`` — pure attribute assembly for
  each signal;
* ``_span`` (:class:`SpanRecorder`) / ``_metrics`` (:class:`MetricsRecorder`) —
  the two symmetric signal recorders;
* ``_middleware`` — the thin orchestrator wiring both recorders into the
  request lifecycle;
* ``_url_filter`` — standard-library URL exclusion;
* ``_instrumentor`` — activation via the ``Sanic.__init__`` patch.

Only the names re-exported below are considered public API.
"""

from __future__ import annotations

from ._instrumentor import SanicInstrumentor
from .exceptions import (
    MiddlewareRegistrationError,
    RequestAttributeError,
    SanicConfigurationError,
    SanicInstrumentationError,
)
from .version import __version__

__all__ = [
    "MiddlewareRegistrationError",
    "RequestAttributeError",
    "SanicConfigurationError",
    "SanicInstrumentationError",
    "SanicInstrumentor",
    "__version__",
]
