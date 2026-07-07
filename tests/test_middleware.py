"""Unit tests for :class:`._middleware.SanicOpenTelemetryMiddleware`.

The middleware is a pure orchestrator, so it is tested against lightweight spy
recorders rather than real tracers/meters. This isolates the orchestration
logic — exclusion, per-request state handoff, and the boundary guards — from
the recorders' own behaviour (covered in ``test_span``/``test_metrics``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from opentelemetry.instrumentation.sanic._middleware import (
    SanicOpenTelemetryMiddleware,
)
from opentelemetry.instrumentation.sanic.exceptions import (
    MiddlewareRegistrationError,
    RequestAttributeError,
)


class SpySpanRecorder:
    """Records calls; optionally raises from :meth:`start`."""

    def __init__(self, start_error: Exception | None = None) -> None:
        self.start_calls: list[Any] = []
        self.finish_calls: list[tuple[Any, Any]] = []
        self._start_error = start_error
        self.sentinel = SimpleNamespace(kind="active-span")

    def start(self, request: Any) -> Any:
        self.start_calls.append(request)
        if self._start_error is not None:
            raise self._start_error
        return self.sentinel

    def finish(self, active: Any, response: Any) -> None:
        self.finish_calls.append((active, response))


class SpyMetricsRecorder:
    """Records calls to the metrics side of the lifecycle."""

    def __init__(self) -> None:
        self.start_calls: list[Any] = []
        self.finish_calls: list[tuple[Any, Any, Any]] = []
        self.sentinel = SimpleNamespace(kind="measurement")

    def start(self, request: Any) -> Any:
        self.start_calls.append(request)
        return self.sentinel

    def finish(self, request: Any, response: Any, measurement: Any) -> None:
        self.finish_calls.append((request, response, measurement))


class FakeApp:
    """Records middleware registrations."""

    def __init__(self) -> None:
        self.registered: list[tuple[Any, str]] = []

    def register_middleware(self, handler: Any, attach_to: str) -> None:
        self.registered.append((handler, attach_to))


# --------------------------------------------------------------------------- #
# attach                                                                       #
# --------------------------------------------------------------------------- #
def test_attach_registers_request_then_response_middleware() -> None:
    middleware = SanicOpenTelemetryMiddleware(SpySpanRecorder())
    app = FakeApp()

    middleware.attach(app)

    assert [attach_to for _, attach_to in app.registered] == [
        "request",
        "response",
    ]


def test_attach_rejects_app_without_register_middleware() -> None:
    middleware = SanicOpenTelemetryMiddleware(SpySpanRecorder())
    with pytest.raises(MiddlewareRegistrationError):
        middleware.attach(object())


def test_attach_wraps_registration_type_errors() -> None:
    class BadApp:
        def register_middleware(self, handler: Any, attach_to: str) -> None:
            raise TypeError("unexpected signature")

    middleware = SanicOpenTelemetryMiddleware(SpySpanRecorder())
    with pytest.raises(MiddlewareRegistrationError):
        middleware.attach(BadApp())


# --------------------------------------------------------------------------- #
# on_request                                                                   #
# --------------------------------------------------------------------------- #
def test_on_request_starts_recorders_and_stores_state(make_request) -> None:
    span, metrics = SpySpanRecorder(), SpyMetricsRecorder()
    middleware = SanicOpenTelemetryMiddleware(span, metrics)
    request = make_request()

    middleware.on_request(request)

    assert span.start_calls == [request]
    assert metrics.start_calls == [request]
    assert request.ctx._otel_active_span is span.sentinel
    assert request.ctx._otel_measurement is metrics.sentinel


def test_on_request_skips_excluded_urls(make_request) -> None:
    span, metrics = SpySpanRecorder(), SpyMetricsRecorder()
    middleware = SanicOpenTelemetryMiddleware(
        span, metrics, excluded_urls="/health"
    )

    middleware.on_request(make_request(url="http://testserver/health"))

    assert span.start_calls == []
    assert metrics.start_calls == []


def test_on_request_stores_none_measurement_without_metrics(
    make_request,
) -> None:
    span = SpySpanRecorder()
    middleware = SanicOpenTelemetryMiddleware(span, metrics_recorder=None)
    request = make_request()

    middleware.on_request(request)

    assert request.ctx._otel_active_span is span.sentinel
    assert request.ctx._otel_measurement is None


def test_on_request_swallows_unrecognised_request(make_request) -> None:
    span = SpySpanRecorder(start_error=RequestAttributeError("nope"))
    middleware = SanicOpenTelemetryMiddleware(span)
    request = make_request()

    middleware.on_request(request)  # must not raise

    assert not hasattr(request.ctx, "_otel_active_span")


def test_on_request_swallows_unexpected_errors(make_request) -> None:
    span = SpySpanRecorder(start_error=RuntimeError("boom"))
    middleware = SanicOpenTelemetryMiddleware(span)

    middleware.on_request(make_request())  # boundary guard: must not raise


# --------------------------------------------------------------------------- #
# on_response                                                                  #
# --------------------------------------------------------------------------- #
def test_on_response_finishes_both_recorders(
    make_request, make_response
) -> None:
    span, metrics = SpySpanRecorder(), SpyMetricsRecorder()
    middleware = SanicOpenTelemetryMiddleware(span, metrics)
    request, response = make_request(), make_response()

    middleware.on_request(request)
    middleware.on_response(request, response)

    assert span.finish_calls == [(span.sentinel, response)]
    assert metrics.finish_calls == [(request, response, metrics.sentinel)]


def test_on_response_without_stored_state_is_a_noop(
    make_request, make_response
) -> None:
    span, metrics = SpySpanRecorder(), SpyMetricsRecorder()
    middleware = SanicOpenTelemetryMiddleware(span, metrics)

    # on_request was never called, so request.ctx carries no state.
    middleware.on_response(make_request(), make_response())

    assert span.finish_calls == []
    assert metrics.finish_calls == []


def test_on_response_balances_metrics_when_span_finish_raises(
    make_request, make_response
) -> None:
    class RaisingSpanRecorder(SpySpanRecorder):
        def finish(self, active: Any, response: Any) -> None:
            super().finish(active, response)
            raise RuntimeError("span teardown failed")

    span, metrics = RaisingSpanRecorder(), SpyMetricsRecorder()
    middleware = SanicOpenTelemetryMiddleware(span, metrics)
    request, response = make_request(), make_response()

    middleware.on_request(request)
    middleware.on_response(request, response)  # must not raise

    # Metrics are finalised via ``finally`` even though the span teardown blew
    # up — this is what keeps the active-requests counter balanced.
    assert metrics.finish_calls == [(request, response, metrics.sentinel)]
