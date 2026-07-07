"""The :class:`SanicInstrumentor` entry point and its ``Sanic.__init__`` patch.

Instead of patching version-sensitive internals such as ``handle_request``,
the instrumentor wraps :meth:`sanic.Sanic.__init__` so that every application
attaches OpenTelemetry request/response middleware as it is constructed.

The constructor is patched *in place* rather than swapping in a subclass:
Sanic's ``TouchUp`` metaclass rewrites method bodies keyed on the concrete
application class, so preserving the original class identity is what keeps the
framework working. Because instrumentation happens at *construction* time,
:meth:`SanicInstrumentor.instrument` must run before your application object is
created — exactly what the ``opentelemetry-instrument`` launcher guarantees.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from functools import wraps
from typing import Any

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.metrics import get_meter
from opentelemetry.trace import get_tracer

from ._metrics import MetricsRecorder
from ._middleware import SanicOpenTelemetryMiddleware
from ._span import SpanRecorder
from ._url_filter import ExcludeUrlsInput
from .exceptions import MiddlewareRegistrationError, SanicInstrumentationError
from .package import _instruments
from .version import __version__

__all__ = ["SanicInstrumentor"]

_logger = logging.getLogger(__name__)

# Marks a patched ``__init__`` so instrumentation is idempotent and reversible.
_OTEL_PATCH_FLAG = "_otel_instrumented"

#: Instrumentation scope name reported for all emitted telemetry. Pinned to the
#: package (not this submodule) so it is stable regardless of file layout.
_SCOPE_NAME = "opentelemetry.instrumentation.sanic"


def _build_instrumented_init(
    original_init: Callable[..., None],
    middleware: SanicOpenTelemetryMiddleware,
) -> Callable[..., None]:
    """Wrap ``Sanic.__init__`` to attach middleware after normal construction.

    :param original_init: The unpatched ``Sanic.__init__``.
    :param middleware: The middleware instance to attach to each new app.
    :returns: A drop-in replacement constructor.
    """

    @wraps(original_init)
    def instrumented_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        try:
            middleware.attach(self)
        except MiddlewareRegistrationError:
            _logger.exception(
                "Could not attach OpenTelemetry middleware to Sanic app; "
                "requests from this app will not be instrumented."
            )

    setattr(instrumented_init, _OTEL_PATCH_FLAG, True)
    return instrumented_init


class SanicInstrumentor(BaseInstrumentor):
    """Instruments the Sanic framework to emit OpenTelemetry spans and metrics.

    Use it like any other OpenTelemetry instrumentor::

        SanicInstrumentor().instrument(
            tracer_provider=my_provider,
            meter_provider=my_meter_provider,
            excluded_urls="/health,/metrics",
        )
        ...
        SanicInstrumentor().uninstrument()

    :keyword tracer_provider: An optional
        :class:`~opentelemetry.trace.TracerProvider`; the global provider is
        used when omitted.
    :keyword meter_provider: An optional
        :class:`~opentelemetry.metrics.MeterProvider`; the global provider is
        used when omitted.
    :keyword excluded_urls: Optional comma-separated string or iterable of
        regular-expression patterns; matching request URLs are neither traced
        nor measured.
    """

    def __init__(self) -> None:
        super().__init__()
        self._original_init: Callable[..., None] | None = None

    def instrumentation_dependencies(self) -> Collection[str]:
        """Return the Sanic version specifiers this instrumentor supports.

        :returns: The
            :data:`~opentelemetry.instrumentation.sanic.package._instruments`
            tuple, checked by the base class before instrumenting.
        """
        return _instruments

    def _instrument(self, **kwargs: Any) -> None:
        """Activate instrumentation by wrapping :meth:`sanic.Sanic.__init__`.

        :keyword tracer_provider: Optional tracer provider (see class
            docstring).
        :keyword meter_provider: Optional meter provider (see class docstring).
        :keyword excluded_urls: Optional URL exclusion patterns.
        :raises SanicInstrumentationError: If Sanic cannot be imported.
        :raises SanicConfigurationError: If *excluded_urls* is invalid regex.
        """
        try:
            import sanic
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise SanicInstrumentationError(
                "Sanic is not installed; cannot instrument it."
            ) from exc

        if getattr(sanic.Sanic.__init__, _OTEL_PATCH_FLAG, False):
            # Already patched by another instance; keep the first patch.
            return

        tracer = get_tracer(
            _SCOPE_NAME,
            __version__,
            tracer_provider=kwargs.get("tracer_provider"),
        )
        meter = get_meter(
            _SCOPE_NAME,
            __version__,
            meter_provider=kwargs.get("meter_provider"),
        )
        excluded_urls: ExcludeUrlsInput = kwargs.get("excluded_urls")
        middleware = SanicOpenTelemetryMiddleware(
            SpanRecorder(tracer),
            MetricsRecorder(meter),
            excluded_urls,
        )

        self._original_init = sanic.Sanic.__init__
        sanic.Sanic.__init__ = _build_instrumented_init(
            self._original_init, middleware
        )

    def _uninstrument(self, **kwargs: Any) -> None:
        """Restore the original :meth:`sanic.Sanic.__init__`.

        Applications created while instrumentation was active keep their
        middleware; only newly constructed apps are affected by removal.
        """
        if self._original_init is None:
            return
        try:
            import sanic

            sanic.Sanic.__init__ = self._original_init
        except ImportError:  # pragma: no cover - dependency guard
            _logger.debug(
                "Sanic not importable during uninstrument; skipping."
            )
        finally:
            self._original_init = None
