"""End-to-end tests exercising the whole stack through a real Sanic app.

Unlike the per-module unit tests, these instrument the framework, build a real
application, and drive it via Sanic's built-in ``asgi_client`` (no sockets),
asserting that spans and metrics come out correctly wired together. They are
the integration counterpart to the isolated unit suites.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.semconv._incubating.metrics.http_metrics import (
    HTTP_SERVER_ACTIVE_REQUESTS,
    HTTP_SERVER_REQUEST_BODY_SIZE,
    HTTP_SERVER_RESPONSE_BODY_SIZE,
)
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.semconv.attributes.http_attributes import (
    HTTP_RESPONSE_STATUS_CODE,
    HTTP_ROUTE,
)
from opentelemetry.semconv.metrics.http_metrics import (
    HTTP_SERVER_REQUEST_DURATION,
)
from opentelemetry.trace import SpanKind
from opentelemetry.trace.status import StatusCode

from opentelemetry.instrumentation.sanic import SanicInstrumentor


@pytest.fixture
def traced() -> Iterator[SimpleNamespace]:
    """Instrument Sanic with in-memory span/metric backends.

    Yields a namespace with ``spans`` (an :class:`InMemorySpanExporter`) and
    ``reader`` (an :class:`InMemoryMetricReader`). Instrumentation is torn down
    afterwards so the module-level patch never leaks between tests. ``/health``
    is excluded to exercise the exclusion path end to end.
    """
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])

    instrumentor = SanicInstrumentor()
    instrumentor.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls="/health",
    )
    try:
        yield SimpleNamespace(spans=span_exporter, reader=metric_reader)
    finally:
        instrumentor.uninstrument()
        span_exporter.clear()


def _build_app(name: str):
    """Create a tiny instrumented Sanic app with a handful of routes."""
    from sanic import Sanic
    from sanic.response import json as json_response
    from sanic.response import text

    app = Sanic(name)

    @app.get("/hello/<name>")
    async def hello(request, name: str):
        return json_response({"hello": name})

    @app.post("/echo")
    async def echo(request):
        return text(request.body.decode() if request.body else "")

    @app.get("/boom")
    async def boom(request):
        return text("kaboom", status=500)

    @app.get("/health")
    async def health(request):
        return json_response({"status": "ok"})

    return app


async def test_request_emits_span_and_duration_metric(
    traced, metrics_by_name, point_for_route
) -> None:
    app = _build_app("it-happy")

    _, response = await app.asgi_client.get("/hello/world")

    assert response.status_code == 200
    spans = traced.spans.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].kind is SpanKind.SERVER

    duration = metrics_by_name(traced.reader)[HTTP_SERVER_REQUEST_DURATION]
    point = point_for_route(duration, "/hello/<name")
    assert point is not None
    assert point.count == 1
    assert point.attributes[HTTP_RESPONSE_STATUS_CODE] == 200


async def test_excluded_url_emits_neither_span_nor_metric(
    traced, metrics_by_name
) -> None:
    app = _build_app("it-excluded")

    _, response = await app.asgi_client.get("/health")

    assert response.status_code == 200
    assert traced.spans.get_finished_spans() == ()

    duration = metrics_by_name(traced.reader).get(HTTP_SERVER_REQUEST_DURATION)
    points = [] if duration is None else list(duration.data.data_points)
    assert all(
        not point.attributes.get(HTTP_ROUTE, "").startswith("/health")
        for point in points
    )


async def test_server_error_marks_span_and_metric(
    traced, metrics_by_name, point_for_route
) -> None:
    app = _build_app("it-error")

    _, response = await app.asgi_client.get("/boom")

    assert response.status_code == 500
    span = traced.spans.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR

    point = point_for_route(
        metrics_by_name(traced.reader)[HTTP_SERVER_REQUEST_DURATION], "/boom"
    )
    assert point.attributes[HTTP_RESPONSE_STATUS_CODE] == 500
    assert point.attributes[ERROR_TYPE] == "500"


async def test_request_and_response_body_sizes_recorded(
    traced, metrics_by_name, point_for_route
) -> None:
    app = _build_app("it-body")
    payload = "payload-body"

    await app.asgi_client.post("/echo", data=payload)

    metrics = metrics_by_name(traced.reader)
    request_point = point_for_route(
        metrics[HTTP_SERVER_REQUEST_BODY_SIZE], "/echo"
    )
    response_point = point_for_route(
        metrics[HTTP_SERVER_RESPONSE_BODY_SIZE], "/echo"
    )
    assert request_point.sum == len(payload)
    assert response_point.sum == len(payload)


async def test_active_requests_balances_to_zero(
    traced, metrics_by_name
) -> None:
    app = _build_app("it-active")

    await app.asgi_client.get("/hello/world")

    active = metrics_by_name(traced.reader)[HTTP_SERVER_ACTIVE_REQUESTS]
    assert all(point.value == 0 for point in active.data.data_points)
