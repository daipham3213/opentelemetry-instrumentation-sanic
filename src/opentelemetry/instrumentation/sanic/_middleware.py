"""The request lifecycle, expressed as Sanic middleware.

This module owns exactly one responsibility: turning the request/response
lifecycle of a single Sanic application into OpenTelemetry signals — a server
span and, when a metrics recorder is supplied, the HTTP server metrics. It
knows nothing about *how* it gets attached to an app (that is the
instrumentor's job) nor which instruments exist (that is the recorder's job),
which keeps the concerns loosely coupled and independently testable.
"""

import logging
from typing import Any

from opentelemetry.propagate import extract
from opentelemetry.trace import Span, Tracer
from opentelemetry.trace.status import Status

from opentelemetry import context as otel_context
from opentelemetry import trace

from ._attributes import (
    HTTP_RESPONSE_STATUS_CODE,
    SERVER_SPAN_KIND,
    collect_request_attributes,
    span_name_for,
    status_code_to_status,
)
from ._metrics import RequestMeasurement, SanicMetricsRecorder
from ._url_filter import ExcludeUrlFilter, ExcludeUrlsInput
from .exceptions import MiddlewareRegistrationError, RequestAttributeError

__all__ = ["SanicOpenTelemetryMiddleware"]

_logger = logging.getLogger(__name__)

# Keys under which per-request tracing/metric state is stashed on ``request.ctx``.
_CTX_SPAN = "_otel_span"
_CTX_TOKEN = "_otel_context_token"
_CTX_MEASUREMENT = "_otel_metric"


class SanicOpenTelemetryMiddleware:
    """Creates and finalises a server span for each Sanic request.

    An instance is stateless with respect to individual requests: all
    per-request state lives on ``request.ctx``, so a single middleware object
    can safely serve many concurrent requests and many applications.

    :param tracer: The :class:`~opentelemetry.trace.Tracer` used to create spans.
    :param recorder: Optional
        :class:`~opentelemetry.instrumentation.sanic._metrics.SanicMetricsRecorder`;
        when ``None`` no metrics are emitted (spans only).
    :param excluded_urls: Optional URL patterns to skip; see
        :class:`~opentelemetry.instrumentation.sanic._url_filter.ExcludeUrlFilter`.
        Excluded URLs produce neither spans nor metrics.
    """

    def __init__(
        self,
        tracer: Tracer,
        recorder: SanicMetricsRecorder | None = None,
        excluded_urls: ExcludeUrlsInput = None,
    ) -> None:
        self._tracer = tracer
        self._recorder = recorder
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
                "Application does not expose a callable 'register_middleware'; "
                "the installed Sanic version may be unsupported."
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
        """Start a server span, make it current, and mark the request in-flight.

        Registered as a Sanic ``request`` middleware. Any failure is logged and
        swallowed so that instrumentation never breaks the request pipeline.

        :param request: The incoming Sanic request.
        """
        try:
            url = getattr(request, "url", "") or ""
            if self._excluded_urls.is_excluded(url):
                return

            span = self._tracer.start_span(
                name=span_name_for(request),
                context=extract(getattr(request, "headers", {}) or {}),
                kind=SERVER_SPAN_KIND,
                attributes=collect_request_attributes(request),
            )
            token = otel_context.attach(trace.set_span_in_context(span))
            # Recorder calls are internally guarded, so the span/token are
            # always stored and will be finalised in on_response.
            measurement = (
                self._recorder.on_request(request)
                if self._recorder is not None
                else None
            )
            self._store(request, span, token, measurement)
        except RequestAttributeError:
            _logger.debug("Skipping tracing: unrecognised request object.")
        except Exception:
            _logger.exception("Unexpected error while starting Sanic span.")

    def on_response(self, request: Any, response: Any) -> None:
        """Finalise the span started in :meth:`on_request`.

        Registered as a Sanic ``response`` middleware. Sanic runs response
        middleware even for error responses, so 5xx outcomes are captured here.

        :param request: The Sanic request the response belongs to.
        :param response: The outgoing Sanic response.
        """
        span, token, measurement = self._retrieve(request)
        if span is None:
            return
        try:
            status_code = getattr(response, "status", None)
            if isinstance(status_code, int) and span.is_recording():
                span.set_attribute(HTTP_RESPONSE_STATUS_CODE, status_code)
                span.set_status(Status(status_code_to_status(status_code)))
        except Exception:
            _logger.exception("Unexpected error while finishing Sanic span.")
        finally:
            span.end()
            if token is not None:
                otel_context.detach(token)
            if self._recorder is not None:
                self._recorder.on_response(request, response, measurement)

    # -- per-request state helpers -------------------------------------------

    @staticmethod
    def _store(
        request: Any,
        span: Span,
        token: object,
        measurement: RequestMeasurement | None,
    ) -> None:
        ctx = getattr(request, "ctx", None)
        if ctx is None:  # pragma: no cover - defensive; real requests have ctx
            return
        setattr(ctx, _CTX_SPAN, span)
        setattr(ctx, _CTX_TOKEN, token)
        setattr(ctx, _CTX_MEASUREMENT, measurement)

    @staticmethod
    def _retrieve(
        request: Any,
    ) -> tuple[Span | None, object | None, RequestMeasurement | None]:
        ctx = getattr(request, "ctx", None)
        if ctx is None:
            return None, None, None
        return (
            getattr(ctx, _CTX_SPAN, None),
            getattr(ctx, _CTX_TOKEN, None),
            getattr(ctx, _CTX_MEASUREMENT, None),
        )
