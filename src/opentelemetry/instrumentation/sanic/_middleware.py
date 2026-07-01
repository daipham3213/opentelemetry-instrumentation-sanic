"""The span lifecycle, expressed as Sanic middleware.

This module owns exactly one responsibility: turning the request/response
lifecycle of a single Sanic application into OpenTelemetry spans. It knows
nothing about *how* it gets attached to an app (that is the instrumentor's
job), which keeps the two concerns loosely coupled and independently testable.
"""

from __future__ import annotations

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
from ._url_filter import ExcludeUrlFilter, ExcludeUrlsInput
from .exceptions import MiddlewareRegistrationError, RequestAttributeError

__all__ = ["SanicOpenTelemetryMiddleware"]

_logger = logging.getLogger(__name__)

# Keys under which per-request tracing state is stashed on ``request.ctx``.
_CTX_SPAN = "_otel_span"
_CTX_TOKEN = "_otel_context_token"


class SanicOpenTelemetryMiddleware:
    """Creates and finalises a server span for each Sanic request.

    An instance is stateless with respect to individual requests: all
    per-request state lives on ``request.ctx``, so a single middleware object
    can safely serve many concurrent requests and many applications.

    :param tracer: The :class:`~opentelemetry.trace.Tracer` used to create spans.
    :param excluded_urls: Optional URL patterns to skip; see
        :class:`~opentelemetry.instrumentation.sanic._url_filter.ExcludeUrlFilter`.
    """

    def __init__(self, tracer: Tracer, excluded_urls: ExcludeUrlsInput = None) -> None:
        self._tracer = tracer
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
        """Start a server span and make it the current context.

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
            self._store(request, span, token)
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
        span, token = self._retrieve(request)
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

    # -- per-request state helpers -------------------------------------------

    @staticmethod
    def _store(request: Any, span: Span, token: object) -> None:
        ctx = getattr(request, "ctx", None)
        if ctx is None:  # pragma: no cover - defensive; real requests have ctx
            return
        setattr(ctx, _CTX_SPAN, span)
        setattr(ctx, _CTX_TOKEN, token)

    @staticmethod
    def _retrieve(request: Any) -> tuple[Span | None, object | None]:
        ctx = getattr(request, "ctx", None)
        if ctx is None:
            return None, None
        return getattr(ctx, _CTX_SPAN, None), getattr(ctx, _CTX_TOKEN, None)
