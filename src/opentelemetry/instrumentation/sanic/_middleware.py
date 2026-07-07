"""The request lifecycle, expressed as Sanic middleware.

This module owns exactly one responsibility: driving the request/response
lifecycle of a single Sanic application and delegating each telemetry signal to
its recorder. It knows nothing about *how* it is attached to an app (the
instrumentor's job) nor which spans/instruments exist (each recorder's job),
which keeps the concerns loosely coupled and independently testable.

The two Sanic callbacks are the boundary between the host application and this
instrumentation, so — and only here — they deliberately wrap their work in a
catch-all ``except``. A telemetry failure must never propagate into request
handling; the exception is logged and swallowed instead.
"""

from __future__ import annotations

import logging
from typing import Any

from . import _request
from ._metrics import MetricsRecorder, RequestMeasurement
from ._span import ActiveSpan, SpanRecorder
from ._url_filter import ExcludeUrlFilter, ExcludeUrlsInput
from .exceptions import MiddlewareRegistrationError, RequestAttributeError

__all__ = ["SanicOpenTelemetryMiddleware"]

_logger = logging.getLogger(__name__)

# Keys under which per-request telemetry state is stashed on ``request.ctx``.
_CTX_SPAN = "_otel_active_span"
_CTX_MEASUREMENT = "_otel_measurement"


class SanicOpenTelemetryMiddleware:
    """Drives the per-request span and metric recorders for one Sanic app.

    An instance is stateless with respect to individual requests: all
    per-request state lives on ``request.ctx``, so a single middleware object
    can safely serve many concurrent requests and many applications.

    :param span_recorder: The
        :class:`~opentelemetry.instrumentation.sanic._span.SpanRecorder` that
        emits the server span.
    :param metrics_recorder: Optional
        :class:`~opentelemetry.instrumentation.sanic._metrics.MetricsRecorder`;
        when ``None`` no metrics are emitted (spans only).
    :param excluded_urls: Optional URL patterns to skip; see
        :class:`~opentelemetry.instrumentation.sanic._url_filter.ExcludeUrlFilter`.
        Excluded URLs produce neither spans nor metrics.
    :raises SanicConfigurationError: If *excluded_urls* is not valid
        regular-expression syntax.
    """

    def __init__(
        self,
        span_recorder: SpanRecorder,
        metrics_recorder: MetricsRecorder | None = None,
        excluded_urls: ExcludeUrlsInput = None,
    ) -> None:
        self._span_recorder = span_recorder
        self._metrics_recorder = metrics_recorder
        self._excluded_urls = ExcludeUrlFilter(excluded_urls)

    def attach(self, app: Any) -> None:
        """Register the request/response hooks on a Sanic application.

        :param app: A Sanic application instance.
        :raises MiddlewareRegistrationError: If the app does not expose a
            compatible ``register_middleware`` method.
        """
        register = getattr(app, "register_middleware", None)
        if not callable(register):
            raise MiddlewareRegistrationError(
                "Application does not expose a callable "
                "'register_middleware'; the installed Sanic version may be "
                "unsupported."
            )
        try:
            register(self.on_request, attach_to="request")
            register(self.on_response, attach_to="response")
        except (TypeError, ValueError) as exc:  # narrow: bad signature/args
            raise MiddlewareRegistrationError(
                "Failed to register OpenTelemetry middleware on the Sanic app."
            ) from exc

    # -- Sanic middleware callbacks ------------------------------------------

    def on_request(self, request: Any) -> None:
        """Start the span and metric measurement for an incoming request.

        Registered as a Sanic ``request`` middleware. See the module docstring
        for why failures are caught and swallowed here.

        :param request: The incoming Sanic request.
        """
        try:
            if self._excluded_urls.is_excluded(_request.url(request) or ""):
                return
            active_span = self._span_recorder.start(request)
            measurement = (
                self._metrics_recorder.start(request)
                if self._metrics_recorder is not None
                else None
            )
            self._store(request, active_span, measurement)
        except RequestAttributeError:
            _logger.debug(
                "Skipping instrumentation: unrecognised request object."
            )
        except Exception:  # boundary guard: telemetry must not break requests
            _logger.exception(
                "Unexpected error while starting Sanic telemetry."
            )

    def on_response(self, request: Any, response: Any) -> None:
        """Finalise the span and metrics started in :meth:`on_request`.

        Registered as a Sanic ``response`` middleware. Sanic runs response
        middleware even for error responses, so 5xx outcomes are captured here.
        The span is finalised first, but the metric recorder is always invoked
        afterwards (via ``finally``) so the active-requests counter balances
        even if finalising the span fails.

        :param request: The Sanic request the response belongs to.
        :param response: The outgoing Sanic response.
        """
        active_span, measurement = self._retrieve(request)
        if active_span is None and measurement is None:
            return
        try:
            try:
                self._span_recorder.finish(active_span, response)
            finally:
                if self._metrics_recorder is not None:
                    self._metrics_recorder.finish(
                        request, response, measurement
                    )
        except Exception:  # boundary guard: telemetry must not break requests
            _logger.exception(
                "Unexpected error while finishing Sanic telemetry."
            )

    # -- per-request state helpers -------------------------------------------

    @staticmethod
    def _store(
        request: Any,
        active_span: ActiveSpan,
        measurement: RequestMeasurement | None,
    ) -> None:
        ctx = getattr(request, "ctx", None)
        if ctx is None:  # pragma: no cover - defensive; real requests have ctx
            return
        setattr(ctx, _CTX_SPAN, active_span)
        setattr(ctx, _CTX_MEASUREMENT, measurement)

    @staticmethod
    def _retrieve(
        request: Any,
    ) -> tuple[ActiveSpan | None, RequestMeasurement | None]:
        ctx = getattr(request, "ctx", None)
        if ctx is None:
            return None, None
        return (
            getattr(ctx, _CTX_SPAN, None),
            getattr(ctx, _CTX_MEASUREMENT, None),
        )
