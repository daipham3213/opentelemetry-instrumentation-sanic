"""Own the server-span half of the request lifecycle.

:class:`SpanRecorder` turns a request/response pair into a single OpenTelemetry
*server span*: it starts the span (restoring any propagated parent context and
making the new span current) and later finalises it with the response status.
It knows nothing about *how* it is invoked — that is the middleware's job — nor
about metrics, which keeps the two signals independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opentelemetry.propagate import extract
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_RESPONSE_STATUS_CODE,
)
from opentelemetry.trace import Span, Tracer
from opentelemetry.trace.status import Status

from opentelemetry import context as otel_context
from opentelemetry import trace

from . import _request
from ._span_attributes import (
    SERVER_SPAN_KIND,
    collect_request_attributes,
    span_name_for,
    status_code_to_status,
)

__all__ = ["ActiveSpan", "SpanRecorder"]


@dataclass(slots=True)
class ActiveSpan:
    """A started span plus the token needed to detach its attached context.

    Held opaquely by the middleware on ``request.ctx`` between
    :meth:`SpanRecorder.start` and :meth:`SpanRecorder.finish`.

    :ivar span: The in-flight server span.
    :ivar context_token: The token returned when the span's context was
        attached, used to detach it symmetrically when the span ends.
    """

    span: Span
    context_token: object


class SpanRecorder:
    """Creates and finalises the server span for a single request.

    A single instance is stateless with respect to individual requests — all
    per-request state lives in the :class:`ActiveSpan` it returns — so one
    recorder can safely serve many concurrent requests and applications.

    :param tracer: The :class:`~opentelemetry.trace.Tracer` used to create
        spans.
    """

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def start(self, request: Any) -> ActiveSpan:
        """Start a server span, make it the current span, and return its handle.

        :param request: The incoming Sanic request.
        :returns: An :class:`ActiveSpan` to hand back to :meth:`finish`.
        :raises RequestAttributeError: If *request* is not a Sanic request.
        """
        span = self._tracer.start_span(
            name=span_name_for(request),
            context=extract(_request.headers(request)),
            kind=SERVER_SPAN_KIND,
            attributes=collect_request_attributes(request),
        )
        token = otel_context.attach(trace.set_span_in_context(span))
        return ActiveSpan(span, token)

    def finish(self, active: ActiveSpan | None, response: Any) -> None:
        """Finalise the span started by :meth:`start`.

        Records the response status, then always ends the span and detaches its
        context — even if reading the response status fails.

        :param active: The handle returned by the paired :meth:`start`, or
            ``None`` to skip (no span was started).
        :param response: The outgoing Sanic response.
        """
        if active is None:
            return
        span = active.span
        try:
            status_code = _request.response_status(response)
            if status_code is not None and span.is_recording():
                span.set_attribute(HTTP_RESPONSE_STATUS_CODE, status_code)
                span.set_status(Status(status_code_to_status(status_code)))
        finally:
            span.end()
            otel_context.detach(active.context_token)
